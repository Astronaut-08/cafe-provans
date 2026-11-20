"""Страва в закладі: власна ціна й доступність (адмін) та стоп-лист (офіціант)."""
import pytest
from sqlalchemy import select

from app.db.enums import UserRole
from app.db.models.dish import Dish
from app.db.models.dish_location import DishLocation
from tests.factories import bearer, make_category, make_dish, make_location, make_user

DISHES = '/api/v1/dishes'


def put_url(dish_id: int, location_id: int) -> str:
    return f'{DISHES}/{dish_id}/locations/{location_id}'


def stop_url(location_id: int, dish_id: int) -> str:
    return f'/api/v1/locations/{location_id}/menu/{dish_id}/availability'


def menu_dishes(body: dict) -> dict[str, dict]:
    return {dish['name']: dish for category in body['categories'] for dish in category['dishes']}


async def menu_of(client, location_id: int, **params) -> dict[str, dict]:
    return menu_dishes((await client.get(f'/api/v1/locations/{location_id}/menu', params=params)).json())


# ---------- PUT / DELETE (адмін) ----------

async def test_put_adds_dish_to_location_with_own_price(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', '180')
    assert await menu_of(client, loc.id) == {}

    response = await client.put(put_url(dish.id, loc.id), json={'price_override': 200})
    assert response.status_code == 200
    assert response.json() == {'location_id': loc.id, 'is_available': True, 'price_override': 200.0}
    assert (await menu_of(client, loc.id))['Маргарита']['price'] == 200.0


async def test_put_overwrites_the_whole_record(client, db_session, login_as):
    # PUT це повний запис: пропущена власна ціна означає «знову базова», а не «лишити як було»
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', '180', sell_in=[loc])
    await client.put(put_url(dish.id, loc.id), json={'price_override': 200, 'is_available': False})

    response = await client.put(put_url(dish.id, loc.id), json={})
    assert response.json() == {'location_id': loc.id, 'is_available': True, 'price_override': None}
    shown = (await menu_of(client, loc.id))['Маргарита']
    assert (shown['price'], shown['is_available']) == (180.0, True)
    assert len((await db_session.scalars(select(DishLocation).where(DishLocation.dish_id == dish.id))).all()) == 1


async def test_put_only_touches_the_given_location(client, db_session, login_as):
    login_as(UserRole.admin)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', '180', sell_in=[a, b])
    await client.put(put_url(dish.id, a.id), json={'price_override': 250, 'is_available': False})

    assert (await menu_of(client, a.id))['Маргарита']['price'] == 250.0
    shown_b = (await menu_of(client, b.id))['Маргарита']
    assert (shown_b['price'], shown_b['is_available']) == (180.0, True)


@pytest.mark.parametrize('body', [{'price_override': -1}, {'price_override': 100_001}, {'price_override': '1.234'},
                                  {'is_available': 'maybe'}, {'unknown': 1}])
async def test_put_rejects_invalid_body(client, db_session, login_as, body):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session))
    assert (await client.put(put_url(dish.id, loc.id), json=body)).status_code == 422


async def test_put_unknown_dish_or_location_is_404(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session))
    assert (await client.put(put_url(9999, loc.id), json={})).status_code == 404
    assert (await client.put(put_url(dish.id, 9999), json={})).status_code == 404


async def test_put_works_for_inactive_location(client, db_session, login_as):
    # адмін готує меню закладу ще до того, як його відкрито для гостей
    login_as(UserRole.admin)
    loc = await make_location(db_session, active=False)
    dish = await make_dish(db_session, await make_category(db_session))
    assert (await client.put(put_url(dish.id, loc.id), json={})).status_code == 200


async def test_delete_removes_dish_from_one_location_only(client, db_session, login_as):
    login_as(UserRole.admin)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', sell_in=[a, b])

    assert (await client.delete(put_url(dish.id, a.id))).status_code == 204
    assert await menu_of(client, a.id) == {}
    assert 'Маргарита' in await menu_of(client, b.id)
    assert (await db_session.get(Dish, dish.id)) is not None            # сама страва лишилась
    assert (await client.delete(put_url(dish.id, a.id))).status_code == 404   # повторно: вже немає


async def test_location_endpoints_require_admin(client, db_session):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[loc])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=loc)
    assert (await client.put(put_url(dish.id, loc.id), json={})).status_code == 401
    assert (await client.put(put_url(dish.id, loc.id), json={}, headers=bearer(waiter))).status_code == 403
    assert (await client.delete(put_url(dish.id, loc.id), headers=bearer(waiter))).status_code == 403


# ---------- стоп-лист ----------

async def test_waiter_toggles_stop_list_in_own_location(client, db_session):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', sell_in=[loc])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=loc)

    response = await client.patch(stop_url(loc.id, dish.id), json={'is_available': False}, headers=bearer(waiter))
    assert response.status_code == 200
    assert response.json() == {'location_id': loc.id, 'is_available': False, 'price_override': None}
    assert (await menu_of(client, loc.id))['Маргарита']['is_available'] is False
    assert await menu_of(client, loc.id, available_only='true') == {}

    await client.patch(stop_url(loc.id, dish.id), json={'is_available': True}, headers=bearer(waiter))
    assert (await menu_of(client, loc.id))['Маргарита']['is_available'] is True


async def test_stop_list_is_per_location_and_does_not_touch_global_flag_or_price(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', '180', sell_in=[a, b])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=a)
    await client.put(put_url(dish.id, a.id), json={'price_override': 250}, headers=bearer(
        await make_user(db_session, 'boss', role=UserRole.admin)))

    await client.patch(stop_url(a.id, dish.id), json={'is_available': False}, headers=bearer(waiter))

    assert (await menu_of(client, a.id))['Маргарита']['is_available'] is False
    assert (await menu_of(client, b.id))['Маргарита']['is_available'] is True      # інший заклад не зачеплено
    assert (await menu_of(client, a.id))['Маргарита']['price'] == 250.0            # власна ціна збереглась
    await db_session.refresh(dish)
    assert dish.is_available is True                                                # глобальний прапорець теж


async def test_waiter_cannot_touch_another_location(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[a, b])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=a)

    response = await client.patch(stop_url(b.id, dish.id), json={'is_available': False}, headers=bearer(waiter))
    assert (response.status_code, response.json()['error']['code']) == (403, 'other_location')
    row = await db_session.scalar(select(DishLocation).where(DishLocation.location_id == b.id))
    await db_session.refresh(row)
    assert row.is_available is True


async def test_waiter_without_location_cannot_use_stop_list(client, db_session):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[loc])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter)               # без закладу
    response = await client.patch(stop_url(loc.id, dish.id), json={'is_available': False}, headers=bearer(waiter))
    assert (response.status_code, response.json()['error']['code']) == (403, 'no_location')


async def test_admin_uses_stop_list_in_any_location(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', sell_in=[loc])
    assert (await client.patch(stop_url(loc.id, dish.id), json={'is_available': False})).status_code == 200
    assert (await menu_of(client, loc.id))['Маргарита']['is_available'] is False


async def test_chef_and_guests_cannot_use_stop_list(client, db_session):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[loc])
    chef = await make_user(db_session, 'chef', role=UserRole.chef, location=loc)
    assert (await client.patch(stop_url(loc.id, dish.id), json={'is_available': False})).status_code == 401
    assert (await client.patch(stop_url(loc.id, dish.id), json={'is_available': False},
                               headers=bearer(chef))).status_code == 403


async def test_stop_list_for_dish_not_in_location_is_404(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[b])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=a)
    headers = bearer(waiter)
    assert (await client.patch(stop_url(a.id, dish.id), json={'is_available': False}, headers=headers)).status_code == 404
    assert (await client.patch(stop_url(a.id, 9999), json={'is_available': False}, headers=headers)).status_code == 404


@pytest.mark.parametrize('body', [{}, {'is_available': None}, {'available': False}, None])
async def test_stop_list_rejects_invalid_body(client, db_session, body):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), sell_in=[loc])
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter, location=loc)
    response = await client.patch(stop_url(loc.id, dish.id), json=body, headers=bearer(waiter))
    assert response.status_code == 422
