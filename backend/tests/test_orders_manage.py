"""Керування замовленням: картка, список, статуси за ролями, оплата на місці, нотатки."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.db.models.order import Order
from app.db.models.payment import Payment
from tests.orders_world import build_world, delivery_payload, pickup_payload

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
async def w(db_session, set_now):
    set_now(NOW)
    return await build_world(db_session, NOW)


async def make(client, w, *, headers=None, location=None, items=None, **kwargs):
    """Створює замовлення через API й повертає його картку."""
    location = location or w.l1
    items = items or [(w.pizza.id, 1)]
    r = await client.post('/api/v1/orders', json=pickup_payload(location.id, items, **kwargs), headers=headers or w.h.waiter)
    assert r.status_code == 201, r.text
    return r.json()


async def make_delivery(client, w):
    r = await client.post('/api/v1/orders', json=delivery_payload(w.l1.id, [(w.pizza.id, 2)]), headers=w.h.waiter)
    assert r.status_code == 201, r.text
    return r.json()


async def move(client, headers, order_id, status, comment=None):
    return await client.post(f'/api/v1/orders/{order_id}/status', json={'status': status, 'comment': comment}, headers=headers)


async def pay(client, headers, order_id):
    return await client.post(f'/api/v1/orders/{order_id}/payment/confirm', headers=headers)


async def advance(client, w, order_id, *statuses):
    for status in statuses:
        r = await move(client, w.h.waiter, order_id, status)
        assert r.status_code == 200, r.text


# ================= картка =================

async def test_get_order_returns_the_full_card(client, w):
    created = await make(client, w, name='Марія', items=[(w.pizza.id, 1), (w.cola.id, 2)])
    r = await client.get(f'/api/v1/orders/{created["id"]}', headers=w.h.waiter)
    assert r.status_code == 200
    assert r.json() == created
    assert [i['name'] for i in r.json()['items']] == ['Маргарита', 'Кола']      # позиції в порядку замовлення


async def test_allowed_statuses_depend_on_the_role(client, w):
    order = await make(client, w)
    oid = order['id']
    await advance(client, w, oid, 'confirmed')
    by_role = {
        role: (await client.get(f'/api/v1/orders/{oid}', headers=getattr(w.h, role))).json()['allowed_statuses']
        for role in ('waiter', 'chef', 'admin')
    }
    assert by_role == {'waiter': ['preparing', 'cancelled'], 'chef': ['preparing'], 'admin': ['preparing', 'cancelled']}


async def test_get_order_access(client, w):
    oid = (await make(client, w))['id']
    assert (await client.get(f'/api/v1/orders/{oid}')).status_code == 401
    assert (await client.get(f'/api/v1/orders/{oid}', headers=w.h.chef)).status_code == 200
    assert (await client.get(f'/api/v1/orders/{oid}', headers=w.h.admin)).status_code == 200
    other = await client.get(f'/api/v1/orders/{oid}', headers=w.h.waiter2)
    assert other.status_code == 403 and other.json()['error']['code'] == 'other_location'
    assert (await client.get(f'/api/v1/orders/{oid}', headers=w.h.chef2)).status_code == 403
    assert (await client.get(f'/api/v1/orders/{oid}', headers=w.h.waiter_free)).json()['error']['code'] == 'no_location'


@pytest.mark.parametrize('order_id, code', [(999_999, 404), (0, 422), (2_147_483_648, 422), ('abc', 422)])
async def test_get_order_bad_ids(client, w, order_id, code):
    assert (await client.get(f'/api/v1/orders/{order_id}', headers=w.h.admin)).status_code == code


# ================= список =================

async def test_list_is_scoped_to_the_staff_location(client, w):
    mine = await make(client, w)
    theirs = await make(client, w, headers=w.h.waiter2, location=w.l2)
    for role, expected in (('waiter', mine), ('chef', mine), ('waiter2', theirs), ('chef2', theirs)):
        r = await client.get('/api/v1/orders', headers=getattr(w.h, role))
        assert [o['id'] for o in r.json()] == [expected['id']], role
    admin = await client.get('/api/v1/orders', headers=w.h.admin)
    assert {o['id'] for o in admin.json()} == {mine['id'], theirs['id']}


async def test_admin_can_filter_by_location(client, w):
    mine = await make(client, w)
    await make(client, w, headers=w.h.waiter2, location=w.l2)
    r = await client.get(f'/api/v1/orders?location_id={w.l1.id}', headers=w.h.admin)
    assert [o['id'] for o in r.json()] == [mine['id']]


async def test_waiter_cannot_ask_for_another_location(client, w):
    r = await client.get(f'/api/v1/orders?location_id={w.l2.id}', headers=w.h.waiter)
    assert r.status_code == 403 and r.json()['error']['code'] == 'other_location'
    r = await client.get(f'/api/v1/orders?location_id={w.l1.id}', headers=w.h.waiter)       # свій: можна
    assert r.status_code == 200


async def test_waiter_without_location_cannot_list(client, w):
    r = await client.get('/api/v1/orders', headers=w.h.waiter_free)
    assert r.status_code == 403 and r.json()['error']['code'] == 'no_location'


async def test_list_requires_a_login(client, w):
    assert (await client.get('/api/v1/orders')).status_code == 401


async def test_list_row_content(client, w):
    created = await make(client, w, items=[(w.pizza.id, 2), (w.cola.id, 3)], name='Марія')
    row = (await client.get('/api/v1/orders', headers=w.h.waiter)).json()[0]
    assert row == {
        'id': created['id'], 'order_number': created['order_number'], 'location_id': w.l1.id,
        'source': 'waiter', 'fulfillment_type': 'pickup', 'status': 'new', 'payment_status': 'pending',
        'customer_name': 'Марія', 'customer_phone': '+380671234567', 'delivery_address': None,
        'total_price': 550.0, 'items_count': 5, 'created_at': created['created_at'],
    }


async def test_list_is_newest_first_and_paginated(client, db_session, w):
    ids = [(await make(client, w, items=[(w.cola.id, 1)]))['id'] for _ in range(5)]
    # однакового created_at у тесті бути не повинно: рознесемо в часі, щоб перевірити саме сортування за часом
    for index, oid in enumerate(ids):
        await db_session.execute(update(Order).where(Order.id == oid).values(created_at=NOW + timedelta(minutes=index)))
    await db_session.commit()
    full = [o['id'] for o in (await client.get('/api/v1/orders', headers=w.h.waiter)).json()]
    assert full == ids[::-1]
    page = [o['id'] for o in (await client.get('/api/v1/orders?limit=2&offset=1', headers=w.h.waiter)).json()]
    assert page == ids[::-1][1:3]


async def test_list_with_equal_timestamps_has_a_stable_order_across_pages(client, db_session, w):
    ids = [(await make(client, w, items=[(w.cola.id, 1)]))['id'] for _ in range(14)]
    await db_session.execute(update(Order).values(created_at=NOW))      # усі в одну мить: вирішує лише id
    await db_session.commit()
    seen = []
    for offset in (0, 5, 10):
        page = await client.get(f'/api/v1/orders?limit=5&offset={offset}', headers=w.h.waiter)
        seen += [o['id'] for o in page.json()]
    assert seen == ids[::-1]          # без дублів і пропусків між сторінками


@pytest.mark.parametrize('query', ['limit=0', 'limit=201', 'offset=-1', 'status=bogus', 'fulfillment_type=x',
                                   'payment_status=x', 'created_from=2026-11-20T00:00:00',
                                   'created_to=2026-11-20T00:00:00', 'created_to=not-a-date', 'location_id=0', f'search={"x" * 51}'])
async def test_list_rejects_bad_query(client, w, query):
    assert (await client.get(f'/api/v1/orders?{query}', headers=w.h.admin)).status_code == 422


async def test_list_filters_by_status(client, w):
    a = await make(client, w)
    b = await make(client, w)
    c = await make(client, w)
    await advance(client, w, b['id'], 'confirmed')
    await advance(client, w, c['id'], 'cancelled')

    async def ids(query):
        return {o['id'] for o in (await client.get(f'/api/v1/orders?{query}', headers=w.h.waiter)).json()}

    assert await ids('status=new') == {a['id']}
    assert await ids('status=new&status=confirmed') == {a['id'], b['id']}
    assert await ids('status=cancelled') == {c['id']}
    assert await ids('active=true') == {a['id'], b['id']}            # без скасованих і завершених
    assert await ids('active=true&status=cancelled') == set()        # фільтри діють разом
    assert await ids('') == {a['id'], b['id'], c['id']}


async def test_list_filters_by_fulfillment_and_payment(client, w):
    pickup = await make(client, w)
    delivery = await make_delivery(client, w)
    await pay(client, w.h.waiter, delivery['id'])

    async def ids(query):
        return {o['id'] for o in (await client.get(f'/api/v1/orders?{query}', headers=w.h.waiter)).json()}

    assert await ids('fulfillment_type=delivery') == {delivery['id']}
    assert await ids('fulfillment_type=pickup') == {pickup['id']}
    assert await ids('payment_status=paid') == {delivery['id']}
    assert await ids('payment_status=pending') == {pickup['id']}
    assert await ids('payment_status=unpaid') == set()


async def test_list_filters_by_period(client, db_session, w):
    old = await make(client, w)
    new = await make(client, w)
    await db_session.execute(update(Order).where(Order.id == old['id']).values(created_at=NOW - timedelta(days=3)))
    await db_session.execute(update(Order).where(Order.id == new['id']).values(created_at=NOW))
    await db_session.commit()

    async def ids(query):
        r = await client.get('/api/v1/orders', params=query, headers=w.h.waiter)
        assert r.status_code == 200, r.text
        return {o['id'] for o in r.json()}

    border = (NOW - timedelta(days=1)).isoformat()
    assert await ids({'created_from': border}) == {new['id']}
    assert await ids({'created_to': border}) == {old['id']}
    # межа «від» включна, «до» виключна
    assert await ids({'created_from': NOW.isoformat()}) == {new['id']}
    assert await ids({'created_to': NOW.isoformat()}) == {old['id']}
    assert await ids({'created_from': (NOW - timedelta(days=5)).isoformat(), 'created_to': (NOW + timedelta(days=1)).isoformat()}) == {old['id'], new['id']}


async def test_list_search(client, w):
    marie = await make(client, w, phone='0671234567', name='Марія Коваленко')
    petro = await make(client, w, phone='0509998877', name='Петро')

    async def ids(term):
        r = await client.get('/api/v1/orders', params={'search': term}, headers=w.h.waiter)
        assert r.status_code == 200, r.text
        return {o['id'] for o in r.json()}

    assert await ids(marie['order_number']) == {marie['id']}                 # номер повністю
    assert await ids(str(petro['id']).zfill(6)) == {petro['id']}             # частина номера
    assert await ids('PR-') == {marie['id'], petro['id']}
    assert await ids('0671234567') == {marie['id']}                          # телефон як вводить людина
    assert await ids('067 123') == {marie['id']}                             # з пробілом
    assert await ids('(050) 999-88') == {petro['id']}
    assert await ids('+380509998877') == {petro['id']}
    assert await ids('ковал') == {marie['id']}                               # імʼя без урахування регістру
    assert await ids('ПЕТРО') == {petro['id']}
    assert await ids('невідомий') == set()
    assert await ids('   ') == {marie['id'], petro['id']}                     # порожній пошук = без пошуку


async def test_search_finds_a_literal_backslash_and_wildcard_characters_in_names(client, w):
    slash = await make(client, w, phone='0671111111', name='Ірина\\Марія')
    percent = await make(client, w, phone='0672222222', name='100% гість')
    await make(client, w, phone='0673333333', name='Звичайний')

    async def ids(term):
        r = await client.get('/api/v1/orders', params={'search': term}, headers=w.h.waiter)
        assert r.status_code == 200, r.text
        return {o['id'] for o in r.json()}

    assert await ids('а\\М') == {slash['id']}
    assert await ids('0% г') == {percent['id']}


@pytest.mark.parametrize('term', ['%', '_', '\\', '%%', 'P_-'])
async def test_search_wildcards_are_literal(client, w, term):
    await make(client, w, name='Марія')
    r = await client.get('/api/v1/orders', params={'search': term}, headers=w.h.waiter)
    assert r.status_code == 200 and r.json() == []


# ================= зміна статусу =================

async def test_pickup_full_cycle_with_history(client, w):
    order = await make(client, w, name='Марія')
    oid = order['id']
    await advance(client, w, oid, 'confirmed', 'preparing', 'ready')
    r = await move(client, w.h.waiter, oid, 'completed')
    assert r.status_code == 422 and r.json()['error']['code'] == 'payment_required'
    assert (await pay(client, w.h.waiter, oid)).status_code == 200
    r = await move(client, w.h.waiter, oid, 'completed', 'видано гостю')
    assert r.status_code == 200
    card = r.json()
    assert (card['status'], card['payment_status'], card['allowed_statuses']) == ('completed', 'paid', [])
    assert [h['status'] for h in card['history']] == ['new', 'confirmed', 'preparing', 'ready', 'completed']
    assert card['history'][-1]['comment'] == 'видано гостю'
    assert card['history'][-1]['changed_by'] == {'id': w.waiter.id, 'full_name': 'Оля Офіціант'}
    assert card['payments'][0]['status'] == 'paid'


async def test_delivery_full_cycle(client, w):
    order = await make_delivery(client, w)
    oid = order['id']
    await advance(client, w, oid, 'confirmed', 'preparing', 'ready', 'out_for_delivery')
    assert (await move(client, w.h.waiter, oid, 'completed')).json()['error']['code'] == 'payment_required'
    await pay(client, w.h.waiter, oid)                                       # кур'єр узяв гроші
    r = await move(client, w.h.waiter, oid, 'completed')
    assert r.status_code == 200 and r.json()['status'] == 'completed'


async def test_delivery_cannot_skip_out_for_delivery_and_pickup_cannot_use_it(client, w):
    delivery = await make_delivery(client, w)
    await advance(client, w, delivery['id'], 'confirmed', 'preparing', 'ready')
    await pay(client, w.h.waiter, delivery['id'])
    r = await move(client, w.h.waiter, delivery['id'], 'completed')
    assert r.status_code == 409 and r.json()['error']['code'] == 'invalid_transition'
    assert r.json()['error']['details'] == {'from': 'ready', 'to': 'completed', 'allowed': ['out_for_delivery', 'cancelled']}

    pickup = await make(client, w)
    await advance(client, w, pickup['id'], 'confirmed', 'preparing', 'ready')
    r = await move(client, w.h.waiter, pickup['id'], 'out_for_delivery')
    assert r.status_code == 409


@pytest.mark.parametrize('target', ['preparing', 'ready', 'completed', 'out_for_delivery', 'new'])
async def test_cannot_skip_steps_or_go_back(client, w, target):
    oid = (await make(client, w))['id']
    r = await move(client, w.h.waiter, oid, target)
    assert r.status_code == 409
    assert r.json()['error']['details']['allowed'] == ['confirmed', 'cancelled']


async def test_same_status_again_is_a_conflict(client, w):
    oid = (await make(client, w))['id']
    await advance(client, w, oid, 'confirmed')
    r = await move(client, w.h.waiter, oid, 'confirmed')
    assert r.status_code == 409 and r.json()['error']['code'] == 'invalid_transition'


async def test_final_statuses_cannot_be_left(client, w):
    oid = (await make(client, w))['id']
    await advance(client, w, oid, 'cancelled')
    for target in ('new', 'confirmed', 'completed', 'cancelled'):
        r = await move(client, w.h.admin, oid, target)
        assert r.status_code == 409 and r.json()['error']['details']['allowed'] == []


async def test_unknown_status_is_422_and_unknown_order_is_404(client, w):
    oid = (await make(client, w))['id']
    assert (await move(client, w.h.waiter, oid, 'teleported')).status_code == 422
    assert (await move(client, w.h.waiter, 999_999, 'confirmed')).status_code == 404
    bad = await client.post(f'/api/v1/orders/{oid}/status', json={'status': 'confirmed', 'extra': 1}, headers=w.h.waiter)
    assert bad.status_code == 422
    long_comment = await move(client, w.h.waiter, oid, 'confirmed', 'x' * 251)
    assert long_comment.status_code == 422


async def test_chef_does_the_kitchen_steps_only(client, w):
    oid = (await make(client, w))['id']
    r = await move(client, w.h.chef, oid, 'confirmed')            # приймає офіціант, не кухар
    assert r.status_code == 403 and r.json()['error']['code'] == 'transition_forbidden'
    await advance(client, w, oid, 'confirmed')
    assert (await move(client, w.h.chef, oid, 'cancelled')).status_code == 403
    assert (await move(client, w.h.chef, oid, 'preparing')).status_code == 200
    assert (await move(client, w.h.chef, oid, 'cancelled')).status_code == 403
    assert (await move(client, w.h.chef, oid, 'ready')).status_code == 200
    r = await move(client, w.h.chef, oid, 'completed')
    assert r.status_code == 403 and r.json()['error']['code'] == 'transition_forbidden'
    history = (await client.get(f'/api/v1/orders/{oid}', headers=w.h.chef)).json()['history']
    assert history[-1]['changed_by']['full_name'] == 'Петро Кухар'


async def test_invalid_transition_is_reported_before_role_problem(client, w):
    oid = (await make(client, w))['id']
    r = await move(client, w.h.chef, oid, 'completed')     # такого переходу немає взагалі
    assert r.status_code == 409


async def test_status_change_is_scoped_to_the_location(client, w):
    oid = (await make(client, w))['id']
    r = await move(client, w.h.waiter2, oid, 'confirmed')
    assert r.status_code == 403 and r.json()['error']['code'] == 'other_location'
    assert (await move(client, w.h.chef2, oid, 'confirmed')).status_code == 403
    assert (await move(client, w.h.waiter_free, oid, 'confirmed')).json()['error']['code'] == 'no_location'
    assert (await move(client, w.h.admin, oid, 'confirmed')).status_code == 200


async def test_status_change_requires_login(client, w):
    oid = (await make(client, w))['id']
    r = await client.post(f'/api/v1/orders/{oid}/status', json={'status': 'confirmed'})
    assert r.status_code == 401


async def test_cancel_of_unpaid_order_marks_the_payment_failed(client, w):
    oid = (await make(client, w))['id']
    r = await move(client, w.h.waiter, oid, 'cancelled', 'гість передумав')
    card = r.json()
    assert (card['status'], card['payment_status']) == ('cancelled', 'failed')
    assert card['payments'][0]['status'] == 'failed'
    assert card['history'][-1] == {
        'status': 'cancelled', 'comment': 'гість передумав', 'created_at': card['history'][-1]['created_at'],
        'changed_by': {'id': w.waiter.id, 'full_name': 'Оля Офіціант'},
    }


async def test_cancel_of_paid_order_marks_the_payment_refunded(client, w):
    oid = (await make(client, w))['id']
    await pay(client, w.h.waiter, oid)
    card = (await move(client, w.h.waiter, oid, 'cancelled')).json()
    assert (card['payment_status'], card['payments'][0]['status']) == ('refunded', 'refunded')


async def test_cancel_is_possible_at_every_active_step(client, w):
    for steps in ([], ['confirmed'], ['confirmed', 'preparing'], ['confirmed', 'preparing', 'ready']):
        oid = (await make(client, w))['id']
        await advance(client, w, oid, *steps)
        assert (await move(client, w.h.waiter, oid, 'cancelled')).status_code == 200


# ================= оплата =================

async def test_confirm_payment(client, db_session, w):
    order = await make(client, w, method='terminal')
    r = await pay(client, w.h.waiter, order['id'])
    assert r.status_code == 200
    card = r.json()
    assert (card['payment_status'], card['status']) == ('paid', 'new')       # статус страви не змінився
    assert [(p['provider'], p['status'], p['amount']) for p in card['payments']] == [('terminal', 'paid', 200.0)]
    row = await db_session.scalar(select(Order.payment_status).where(Order.id == order['id']))
    assert row.value == 'paid'


async def test_confirm_payment_twice_is_harmless(client, db_session, w):
    oid = (await make(client, w))['id']
    first = (await pay(client, w.h.waiter, oid)).json()
    second = await pay(client, w.h.waiter, oid)
    assert second.status_code == 200 and second.json() == first
    assert len((await db_session.scalars(select(Payment).where(Payment.order_id == oid))).all()) == 1


async def test_confirm_payment_of_cancelled_order_is_a_conflict(client, w):
    oid = (await make(client, w))['id']
    await advance(client, w, oid, 'cancelled')
    r = await pay(client, w.h.waiter, oid)
    assert r.status_code == 409 and r.json()['error']['code'] == 'order_cancelled'


async def test_confirm_payment_without_a_pending_payment_is_a_conflict(client, db_session, w):
    oid = (await make(client, w))['id']
    await db_session.execute(update(Payment).where(Payment.order_id == oid).values(status='failed'))
    await db_session.execute(update(Order).where(Order.id == oid).values(payment_status='failed'))
    await db_session.commit()
    r = await pay(client, w.h.waiter, oid)
    assert r.status_code == 409 and r.json()['error']['code'] == 'no_pending_payment'


async def test_confirm_payment_permissions(client, w):
    oid = (await make(client, w))['id']
    assert (await client.post(f'/api/v1/orders/{oid}/payment/confirm')).status_code == 401
    assert (await pay(client, w.h.chef, oid)).status_code == 403
    r = await pay(client, w.h.waiter2, oid)
    assert r.status_code == 403 and r.json()['error']['code'] == 'other_location'
    assert (await pay(client, w.h.waiter_free, oid)).json()['error']['code'] == 'no_location'
    assert (await pay(client, w.h.admin, oid)).status_code == 200
    assert (await pay(client, w.h.waiter, 999_999)).status_code == 404


async def test_payment_before_kitchen_is_fine_and_unlocks_completion(client, w):
    oid = (await make(client, w))['id']
    await pay(client, w.h.waiter, oid)                                       # оплатили на касі одразу
    await advance(client, w, oid, 'confirmed', 'preparing', 'ready')
    card = (await client.get(f'/api/v1/orders/{oid}', headers=w.h.waiter)).json()
    assert card['allowed_statuses'] == ['completed', 'cancelled']


async def test_completed_is_not_offered_until_the_order_is_paid(client, w):
    oid = (await make(client, w))['id']
    await advance(client, w, oid, 'confirmed', 'preparing', 'ready')
    unpaid = (await client.get(f'/api/v1/orders/{oid}', headers=w.h.waiter)).json()
    assert unpaid['allowed_statuses'] == ['cancelled']                      # кнопки «Виконано» ще немає
    paid = (await pay(client, w.h.waiter, oid)).json()
    assert paid['allowed_statuses'] == ['completed', 'cancelled']


# ================= нотатки =================

async def test_staff_notes_can_be_set_changed_and_cleared(client, w):
    oid = (await make(client, w))['id']
    url = f'/api/v1/orders/{oid}'
    r = await client.patch(url, json={'staff_notes': '  Алергія на горіхи  '}, headers=w.h.waiter)
    assert r.status_code == 200 and r.json()['staff_notes'] == 'Алергія на горіхи'
    assert (await client.get(url, headers=w.h.chef)).json()['staff_notes'] == 'Алергія на горіхи'
    r = await client.patch(url, json={'staff_notes': ''}, headers=w.h.waiter)
    assert r.json()['staff_notes'] is None
    await client.patch(url, json={'staff_notes': 'ще раз'}, headers=w.h.waiter)
    assert (await client.patch(url, json={'staff_notes': None}, headers=w.h.waiter)).json()['staff_notes'] is None


async def test_staff_notes_validation_and_permissions(client, w):
    oid = (await make(client, w))['id']
    url = f'/api/v1/orders/{oid}'
    assert (await client.patch(url, json={'staff_notes': 'x' * 1001}, headers=w.h.waiter)).status_code == 422
    assert (await client.patch(url, json={}, headers=w.h.waiter)).status_code == 422
    assert (await client.patch(url, json={'staff_notes': 'a', 'status': 'completed'}, headers=w.h.waiter)).status_code == 422
    assert (await client.patch(url, json={'staff_notes': 'a'})).status_code == 401
    assert (await client.patch(url, json={'staff_notes': 'a'}, headers=w.h.chef)).status_code == 403
    r = await client.patch(url, json={'staff_notes': 'a'}, headers=w.h.waiter2)
    assert r.status_code == 403 and r.json()['error']['code'] == 'other_location'
    assert (await client.patch('/api/v1/orders/999999', json={'staff_notes': 'a'}, headers=w.h.waiter)).status_code == 404
