"""/dishes: керування стравами (адмін): список, створення, зміна, видалення, алергени."""
import pytest
from sqlalchemy import select

from app.db.enums import UserRole
from app.db.models.dish import Dish
from app.db.models.dish_allergen import DishAllergen
from app.db.models.dish_location import DishLocation
from tests.factories import (
    make_allergen, make_category, make_dish, make_location, make_order_with, make_promotion, make_user, bearer,
)

URL = '/api/v1/dishes'


def menu_dishes(body: dict) -> dict[str, dict]:
    return {dish['name']: dish for category in body['categories'] for dish in category['dishes']}


# ---------- доступ ----------

async def test_dishes_require_staff_login(client, db_session):
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat)
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json={'category_id': cat.id, 'name': 'X', 'price': 1})).status_code == 401
    assert (await client.patch(f'{URL}/{dish.id}', json={'name': 'Y'})).status_code == 401
    assert (await client.delete(f'{URL}/{dish.id}')).status_code == 401


@pytest.mark.parametrize('role', [UserRole.waiter, UserRole.chef])
async def test_only_admin_manages_dishes(client, db_session, role):
    # офіціант керує лише стоп-листом (див. test_dish_locations), але не самими стравами
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat)
    user = await make_user(db_session, 'staff', role=role)
    headers = bearer(user)
    assert (await client.get(URL, headers=headers)).status_code == 403
    assert (await client.post(URL, headers=headers, json={'category_id': cat.id, 'name': 'X', 'price': 1})).status_code == 403
    assert (await client.patch(f'{URL}/{dish.id}', headers=headers, json={'name': 'Y'})).status_code == 403
    assert (await client.delete(f'{URL}/{dish.id}', headers=headers)).status_code == 403


# ---------- створення ----------

async def test_create_minimal_dish_goes_to_every_location_by_default(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B', active=False)

    response = await client.post(URL, json={'category_id': cat.id, 'name': '  Маргарита  ', 'price': 180})
    assert response.status_code == 201
    body = response.json()
    assert body['name'] == 'Маргарита'                       # пробіли обрізано
    assert body['price'] == 180.0
    assert body['is_available'] is True and body['show_on_home'] is False
    assert body['description'] is None and body['weight'] is None and body['image_url'] is None
    assert body['allergens'] == []
    assert [(loc['location_id'], loc['is_available'], loc['price_override']) for loc in body['locations']] == [
        (a.id, True, None), (b.id, True, None),
    ]


async def test_create_with_all_fields_allergens_and_own_locations(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    gluten = await make_allergen(db_session, 'gluten', 'Глютен')
    milk = await make_allergen(db_session, 'milk', 'Молоко')

    response = await client.post(URL, json={
        'category_id': cat.id, 'name': 'Пепероні', 'price': '220.50', 'description': 'Гостра',
        'weight': 450, 'diameter': 32, 'badge': 'Хіт', 'show_on_home': True,
        'allergen_ids': [milk.id, gluten.id, milk.id],  # повтор не заважає
        'locations': [{'location_id': a.id, 'price_override': 250}, {'location_id': b.id, 'is_available': False}],
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body['price'], body['weight'], body['diameter'], body['badge'], body['show_on_home']) == (
        220.5, 450, 32, 'Хіт', True,
    )
    assert [al['code'] for al in body['allergens']] == ['gluten', 'milk']
    assert [(loc['location_id'], loc['is_available'], loc['price_override']) for loc in body['locations']] == [
        (a.id, True, 250.0), (b.id, False, None),
    ]


async def test_create_with_empty_locations_list_sells_nowhere(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    await make_location(db_session)
    body = (await client.post(URL, json={'category_id': cat.id, 'name': 'Х', 'price': 1, 'locations': []})).json()
    assert body['locations'] == []


async def test_created_dish_appears_in_public_menu_with_location_price(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    await client.post(URL, json={
        'category_id': cat.id, 'name': 'Маргарита', 'price': 180,
        'locations': [{'location_id': a.id}, {'location_id': b.id, 'price_override': 200}],
    })
    assert menu_dishes((await client.get(f'/api/v1/locations/{a.id}/menu')).json())['Маргарита']['price'] == 180.0
    assert menu_dishes((await client.get(f'/api/v1/locations/{b.id}/menu')).json())['Маргарита']['price'] == 200.0


@pytest.mark.parametrize('payload', [
    {'name': '', 'price': 1},                       # порожня назва
    {'name': '   ', 'price': 1},
    {'name': 'X' * 101, 'price': 1},
    {'name': 'X'},                                   # немає ціни
    {'price': 1},                                    # немає назви
    {'name': 'X', 'price': -1},
    {'name': 'X', 'price': 100_001},                 # понад стелю (одруківка)
    {'name': 'X', 'price': '10.123'},                # три знаки після коми
    {'name': 'X', 'price': 'abc'},
    {'name': 'X', 'price': 1, 'weight': 0},
    {'name': 'X', 'price': 1, 'diameter': 201},
    {'name': 'X', 'price': 1, 'description': 'd' * 2001},
    {'name': 'X', 'price': 1, 'badge': 'b' * 201},
    {'name': 'X', 'price': 1, 'image_url': 'http://x/y.jpg'},   # фото лише через завантаження
    {'name': 'X', 'price': 1, 'unknown_field': 1},
    {'name': 'X', 'price': 1, 'locations': [{'location_id': 1}, {'location_id': 1}]},   # заклад двічі
    {'name': 'X', 'price': 1, 'locations': [{'location_id': 1, 'price_override': -5}]},
    {'name': 'X', 'price': 1, 'allergen_ids': [0]},
])
async def test_create_rejects_invalid_payload(client, db_session, login_as, payload):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    response = await client.post(URL, json={'category_id': cat.id, **payload})
    assert response.status_code == 422, response.text
    assert (await db_session.scalars(select(Dish))).all() == []


async def test_create_with_the_same_location_twice_is_422(client, db_session, login_as):
    # заклад існує, тож відхилити має саме перевірка схеми, а не відсутність закладу
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    loc = await make_location(db_session)
    response = await client.post(URL, json={
        'category_id': cat.id, 'name': 'X', 'price': 1,
        'locations': [{'location_id': loc.id}, {'location_id': loc.id, 'price_override': 5}],
    })
    assert response.status_code == 422
    assert (await db_session.scalars(select(Dish))).all() == []


async def test_create_with_blank_description_stores_null(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    body = (await client.post(URL, json={
        'category_id': cat.id, 'name': 'X', 'price': 1, 'description': '   ', 'badge': '',
    })).json()
    assert body['description'] is None and body['badge'] is None


async def test_create_with_zero_price_is_allowed(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    response = await client.post(URL, json={'category_id': cat.id, 'name': 'Соус', 'price': 0})
    assert response.status_code == 201 and response.json()['price'] == 0


async def test_create_with_unknown_references_is_422_and_saves_nothing(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    loc = await make_location(db_session)
    base = {'name': 'X', 'price': 1}

    r = await client.post(URL, json={**base, 'category_id': 9999})
    assert (r.status_code, r.json()['error']['code']) == (422, 'category_not_found')
    r = await client.post(URL, json={**base, 'category_id': cat.id, 'allergen_ids': [9999]})
    assert (r.status_code, r.json()['error']['code']) == (422, 'allergen_not_found')
    r = await client.post(URL, json={**base, 'category_id': cat.id, 'locations': [{'location_id': 9999}]})
    assert (r.status_code, r.json()['error']['code']) == (422, 'location_not_found')

    # жодна з невдалих спроб не залишила «напівстворену» страву
    assert (await db_session.scalars(select(Dish))).all() == []
    assert loc.id  # заклад на місці


# ---------- список і одна страва ----------

async def test_list_shows_every_dish_even_unsold_ones_in_category_order(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    desserts = await make_category(db_session, 'Десерти', 2)
    pizza = await make_category(db_session, 'Піца', 1)
    await make_dish(db_session, desserts, 'Тірамісу')                       # ніде не продається
    await make_dish(db_session, pizza, 'Пепероні', sell_in=[loc], available=False)
    await make_dish(db_session, pizza, 'Маргарита', sell_in=[loc])

    body = (await client.get(URL)).json()
    assert [d['name'] for d in body] == ['Маргарита', 'Пепероні', 'Тірамісу']
    assert 'embedding' not in body[0]


async def test_list_filters(client, db_session, login_as):
    login_as(UserRole.admin)
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    pizza = await make_category(db_session, 'Піца', 1)
    drinks = await make_category(db_session, 'Напої', 2)
    await make_dish(db_session, pizza, 'Маргарита', sell_in=[a, b])
    await make_dish(db_session, pizza, 'Пепероні', sell_in=[a], available=False)
    await make_dish(db_session, drinks, 'Лимонад', sell_in=[b])

    names = lambda body: [d['name'] for d in body]
    assert names((await client.get(URL, params={'category_id': drinks.id})).json()) == ['Лимонад']
    assert names((await client.get(URL, params={'location_id': a.id})).json()) == ['Маргарита', 'Пепероні']
    assert names((await client.get(URL, params={'location_id': b.id})).json()) == ['Маргарита', 'Лимонад']
    assert names((await client.get(URL, params={'is_available': 'false'})).json()) == ['Пепероні']
    assert names((await client.get(URL, params={'is_available': 'true', 'location_id': a.id})).json()) == ['Маргарита']


async def test_list_pagination(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    for name in ['A', 'B', 'C', 'D', 'E']:
        await make_dish(db_session, cat, name)
    names = lambda body: [d['name'] for d in body]
    assert names((await client.get(URL, params={'limit': 2})).json()) == ['A', 'B']
    assert names((await client.get(URL, params={'limit': 2, 'offset': 2})).json()) == ['C', 'D']
    assert names((await client.get(URL, params={'limit': 2, 'offset': 4})).json()) == ['E']
    for bad in ({'limit': 0}, {'limit': 501}, {'offset': -1}, {'category_id': 0}):
        assert (await client.get(URL, params=bad)).status_code == 422


async def test_list_has_allergens_and_locations_of_each_dish(client, db_session, login_as):
    from tests.factories import add_allergen
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    milk = await make_allergen(db_session, 'milk', 'Молоко')
    with_milk = await make_dish(db_session, cat, 'З молоком', sell_in=[loc])
    await add_allergen(db_session, with_milk, milk)
    await make_dish(db_session, cat, 'Без нічого')

    body = {d['name']: d for d in (await client.get(URL)).json()}
    assert [a['code'] for a in body['З молоком']['allergens']] == ['milk']
    assert len(body['З молоком']['locations']) == 1
    assert body['Без нічого']['allergens'] == [] and body['Без нічого']['locations'] == []


async def test_get_one_dish_and_404(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, 'Маргарита', '180', weight=400, description='Класика')
    body = (await client.get(f'{URL}/{dish.id}')).json()
    assert (body['id'], body['name'], body['price'], body['weight'], body['description']) == (
        dish.id, 'Маргарита', 180.0, 400, 'Класика',
    )
    assert (await client.get(f'{URL}/9999')).status_code == 404
    assert (await client.get(f'{URL}/99999999999')).status_code == 422   # поза діапазоном int4


# ---------- зміна ----------

async def test_patch_changes_only_given_fields(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, 'Маргарита', '180', weight=400, description='Класика')

    response = await client.patch(f'{URL}/{dish.id}', json={'price': 190})
    assert response.status_code == 200
    body = response.json()
    assert (body['price'], body['name'], body['weight'], body['description']) == (190.0, 'Маргарита', 400, 'Класика')


async def test_patch_can_clear_optional_fields_with_null(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, 'Маргарита', weight=400, description='Класика')
    body = (await client.patch(f'{URL}/{dish.id}', json={'description': None, 'weight': None})).json()
    assert body['description'] is None and body['weight'] is None


@pytest.mark.parametrize('field', ['name', 'price', 'category_id', 'is_available', 'show_on_home', 'allergen_ids'])
async def test_patch_rejects_null_for_required_fields(client, db_session, login_as, field):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat)
    assert (await client.patch(f'{URL}/{dish.id}', json={field: None})).status_code == 422


async def test_patch_rejects_unknown_and_invalid_fields(client, db_session, login_as):
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat)
    assert (await client.patch(f'{URL}/{dish.id}', json={'image_url': 'x'})).status_code == 422
    assert (await client.patch(f'{URL}/{dish.id}', json={'price': -1})).status_code == 422
    assert (await client.patch(f'{URL}/{dish.id}', json={'name': ''})).status_code == 422


async def test_patch_replaces_the_whole_set_of_allergens(client, db_session, login_as):
    from tests.factories import add_allergen
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    gluten = await make_allergen(db_session, 'gluten', 'Глютен')
    milk = await make_allergen(db_session, 'milk', 'Молоко')
    eggs = await make_allergen(db_session, 'eggs', 'Яйця')
    dish = await make_dish(db_session, cat)
    await add_allergen(db_session, dish, gluten)
    await add_allergen(db_session, dish, milk)

    body = (await client.patch(f'{URL}/{dish.id}', json={'allergen_ids': [milk.id, eggs.id]})).json()
    assert sorted(a['code'] for a in body['allergens']) == ['eggs', 'milk']          # gluten прибрано

    body = (await client.patch(f'{URL}/{dish.id}', json={'price': 5})).json()          # без allergen_ids набір не чіпаємо
    assert sorted(a['code'] for a in body['allergens']) == ['eggs', 'milk']

    body = (await client.patch(f'{URL}/{dish.id}', json={'allergen_ids': []})).json()  # [] = жодного алергена
    assert body['allergens'] == []


async def test_patch_with_unknown_references_changes_nothing(client, db_session, login_as):
    from tests.factories import add_allergen
    login_as(UserRole.admin)
    cat = await make_category(db_session)
    gluten = await make_allergen(db_session, 'gluten', 'Глютен')
    dish = await make_dish(db_session, cat, 'Маргарита', '180')
    await add_allergen(db_session, dish, gluten)

    r = await client.patch(f'{URL}/{dish.id}', json={'category_id': 9999, 'price': 1})
    assert (r.status_code, r.json()['error']['code']) == (422, 'category_not_found')
    r = await client.patch(f'{URL}/{dish.id}', json={'allergen_ids': [9999], 'price': 1})
    assert (r.status_code, r.json()['error']['code']) == (422, 'allergen_not_found')

    body = (await client.get(f'{URL}/{dish.id}')).json()
    assert body['price'] == 180.0                                      # ні ціна, ні алергени не змінились
    assert [a['code'] for a in body['allergens']] == ['gluten']


async def test_patch_moves_dish_to_another_category_and_404(client, db_session, login_as):
    login_as(UserRole.admin)
    a = await make_category(db_session, 'A')
    b = await make_category(db_session, 'B')
    dish = await make_dish(db_session, a)
    assert (await client.patch(f'{URL}/{dish.id}', json={'category_id': b.id})).json()['category_id'] == b.id
    assert (await client.patch(f'{URL}/9999', json={'price': 1})).status_code == 404


async def test_patch_is_reflected_in_public_menu(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, 'Маргарита', '180', sell_in=[loc])
    menu = f'/api/v1/locations/{loc.id}/menu'

    await client.patch(f'{URL}/{dish.id}', json={'price': 195, 'name': 'Маргарита класична', 'is_available': False})
    shown = menu_dishes((await client.get(menu)).json())['Маргарита класична']
    assert (shown['price'], shown['is_available']) == (195.0, False)
    assert menu_dishes((await client.get(menu, params={'available_only': 'true'})).json()) == {}   # стоп-лист


# ---------- видалення ----------

async def test_delete_removes_dish_with_its_allergens_and_locations(client, db_session, login_as):
    from tests.factories import add_allergen
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    milk = await make_allergen(db_session, 'milk', 'Молоко')
    dish = await make_dish(db_session, cat, sell_in=[loc])
    await add_allergen(db_session, dish, milk)
    dish_id = dish.id

    assert (await client.delete(f'{URL}/{dish_id}')).status_code == 204
    assert (await client.get(f'{URL}/{dish_id}')).status_code == 404
    assert (await client.delete(f'{URL}/{dish_id}')).status_code == 404
    assert (await db_session.scalars(select(DishAllergen).where(DishAllergen.dish_id == dish_id))).all() == []
    assert (await db_session.scalars(select(DishLocation).where(DishLocation.dish_id == dish_id))).all() == []
    assert milk.id  # сам алерген лишився


async def test_dish_with_order_history_cannot_be_deleted(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, sell_in=[loc])
    await make_order_with(db_session, dish, loc)

    response = await client.delete(f'{URL}/{dish.id}')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'dish_in_use'
    assert (await client.get(f'{URL}/{dish.id}')).status_code == 200      # страва ціла, разом із закладами
    assert len((await client.get(f'{URL}/{dish.id}')).json()['locations']) == 1


async def test_dish_used_in_promotion_cannot_be_deleted(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    dish = await make_dish(db_session, cat, sell_in=[loc])
    await make_promotion(db_session, locations=[loc], items=[(dish, 1)])

    response = await client.delete(f'{URL}/{dish.id}')
    assert (response.status_code, response.json()['error']['code']) == (409, 'dish_in_use')
