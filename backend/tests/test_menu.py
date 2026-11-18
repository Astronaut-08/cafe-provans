"""GET /locations/{id}/menu: меню конкретного закладу."""
from tests.factories import (
    add_allergen, make_allergen, make_category, make_dish, make_location, set_dish_location,
)


def url(location_id: int) -> str:
    return f'/api/v1/locations/{location_id}/menu'


def dishes_of(body: dict) -> dict[str, dict]:
    return {dish['name']: dish for category in body['categories'] for dish in category['dishes']}


async def test_menu_groups_dishes_by_category_in_sort_order(client, db_session):
    loc = await make_location(db_session)
    desserts = await make_category(db_session, 'Десерти', 2)
    pizza = await make_category(db_session, 'Піца', 1)
    await make_dish(db_session, desserts, 'Тірамісу', '120', sell_in=[loc])
    await make_dish(db_session, pizza, 'Пепероні', '250', sell_in=[loc])
    await make_dish(db_session, pizza, 'Маргарита', '200', sell_in=[loc])

    body = (await client.get(url(loc.id))).json()
    assert body['location_id'] == loc.id
    assert [c['name'] for c in body['categories']] == ['Піца', 'Десерти']
    # усередині категорії за назвою
    assert [d['name'] for d in body['categories'][0]['dishes']] == ['Маргарита', 'Пепероні']


async def test_only_dishes_sold_in_this_location_are_shown(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    cat = await make_category(db_session)
    await make_dish(db_session, cat, 'Лише в A', sell_in=[a])
    await make_dish(db_session, cat, 'В обох', sell_in=[a, b])
    await make_dish(db_session, cat, 'Ніде')

    assert set(dishes_of((await client.get(url(a.id))).json())) == {'Лише в A', 'В обох'}
    assert set(dishes_of((await client.get(url(b.id))).json())) == {'В обох'}


async def test_categories_without_dishes_here_are_not_returned(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    full = await make_category(db_session, 'Є')
    empty_here = await make_category(db_session, 'Немає тут')
    await make_category(db_session, 'Порожня зовсім')
    await make_dish(db_session, full, 'X', sell_in=[a])
    await make_dish(db_session, empty_here, 'Y', sell_in=[b])

    names = [c['name'] for c in (await client.get(url(a.id))).json()['categories']]
    assert names == ['Є']


async def test_price_override_applies_per_location(client, db_session):
    a = await make_location(db_session, 'A')
    b = await make_location(db_session, 'B')
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', '200.00', sell_in=[a, b])
    await set_dish_location(db_session, dish, b, price_override='180.50')

    assert dishes_of((await client.get(url(a.id))).json())['Маргарита']['price'] == 200.0
    assert dishes_of((await client.get(url(b.id))).json())['Маргарита']['price'] == 180.5


async def test_price_is_a_json_number_not_a_string(client, db_session):
    loc = await make_location(db_session)
    await make_dish(db_session, await make_category(db_session), 'X', '199.90', sell_in=[loc])
    price = dishes_of((await client.get(url(loc.id))).json())['X']['price']
    assert isinstance(price, float) and price == 199.9


async def test_availability_requires_both_global_and_local_flags(client, db_session):
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    await make_dish(db_session, cat, 'Усе добре', sell_in=[loc])
    await make_dish(db_session, cat, 'Вимкнено глобально', available=False, sell_in=[loc])
    local_off = await make_dish(db_session, cat, 'Вимкнено тут', sell_in=[loc])
    await set_dish_location(db_session, local_off, loc, available=False)

    dishes = dishes_of((await client.get(url(loc.id))).json())
    assert {name: d['is_available'] for name, d in dishes.items()} == {
        'Усе добре': True, 'Вимкнено глобально': False, 'Вимкнено тут': False,
    }


async def test_available_only_hides_stop_list(client, db_session):
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    await make_dish(db_session, cat, 'Є', sell_in=[loc])
    await make_dish(db_session, cat, 'Нема глобально', available=False, sell_in=[loc])
    local_off = await make_dish(db_session, cat, 'Нема тут', sell_in=[loc])
    await set_dish_location(db_session, local_off, loc, available=False)

    body = (await client.get(url(loc.id), params={'available_only': 'true'})).json()
    assert set(dishes_of(body)) == {'Є'}


async def test_available_only_drops_category_when_all_its_dishes_are_unavailable(client, db_session):
    loc = await make_location(db_session)
    await make_dish(db_session, await make_category(db_session, 'Усе вичерпано'), 'X', available=False, sell_in=[loc])
    body = (await client.get(url(loc.id), params={'available_only': 'true'})).json()
    assert body['categories'] == []


async def test_featured_returns_only_home_page_dishes(client, db_session):
    loc = await make_location(db_session)
    cat = await make_category(db_session)
    await make_dish(db_session, cat, 'На головній', home=True, sell_in=[loc])
    await make_dish(db_session, cat, 'Звичайна', sell_in=[loc])

    body = (await client.get(url(loc.id), params={'featured': 'true'})).json()
    assert set(dishes_of(body)) == {'На головній'}


async def test_allergens_are_attached_to_dishes_sorted_by_name(client, db_session):
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Карбонара', sell_in=[loc])
    await make_dish(db_session, await make_category(db_session, 'Інше'), 'Салат', sell_in=[loc])
    for code, name in [('lactose', 'Лактоза'), ('gluten', 'Глютен')]:
        await add_allergen(db_session, dish, await make_allergen(db_session, code, name))

    dishes = dishes_of((await client.get(url(loc.id))).json())
    assert dishes['Карбонара']['allergens'] == [
        {'code': 'gluten', 'name': 'Глютен'}, {'code': 'lactose', 'name': 'Лактоза'},
    ]
    assert dishes['Салат']['allergens'] == []


async def test_dish_fields_are_exposed_and_embedding_is_not(client, db_session):
    loc = await make_location(db_session)
    await make_dish(db_session, await make_category(db_session), 'Маргарита', '200', weight=450,
                    description='Томати, моцарела', sell_in=[loc])

    dish = dishes_of((await client.get(url(loc.id))).json())['Маргарита']
    assert set(dish) == {
        'id', 'name', 'description', 'price', 'weight', 'diameter', 'image_url', 'badge',
        'is_available', 'show_on_home', 'allergens',
    }
    assert dish['weight'] == 450 and dish['description'] == 'Томати, моцарела'


async def test_empty_menu_is_200_with_no_categories(client, db_session):
    loc = await make_location(db_session)
    r = await client.get(url(loc.id))
    assert r.status_code == 200
    assert r.json() == {'location_id': loc.id, 'categories': []}


async def test_menu_of_inactive_or_unknown_location_is_404(client, db_session):
    inactive = await make_location(db_session, active=False)
    assert (await client.get(url(inactive.id))).status_code == 404
    assert (await client.get(url(999))).status_code == 404


async def test_menu_does_not_load_embedding_column(client, db_session):
    """Вектор на 1536 чисел гостю не потрібен: його не має бути навіть у SQL-запиті меню."""
    from sqlalchemy import event

    statements: list[str] = []
    sync_engine = (await db_session.connection()).sync_connection.engine

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    loc = await make_location(db_session)
    await make_dish(db_session, await make_category(db_session), 'X', sell_in=[loc])

    event.listen(sync_engine, 'before_cursor_execute', capture)
    try:
        assert (await client.get(url(loc.id))).status_code == 200
    finally:
        event.remove(sync_engine, 'before_cursor_execute', capture)

    selects = [s for s in statements if s.lstrip().upper().startswith('SELECT') and 'FROM dishes' in s]
    assert selects, 'очікували хоча б один запит до dishes'
    assert not any('embedding' in s for s in selects)
