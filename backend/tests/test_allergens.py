"""GET /allergens: довідник алергенів."""
from tests.factories import make_allergen

URL = '/api/v1/allergens'


async def test_list_is_sorted_by_name(client, db_session):
    await make_allergen(db_session, 'nuts', 'Горіхи')
    await make_allergen(db_session, 'gluten', 'Глютен')
    await make_allergen(db_session, 'lactose', 'Лактоза')

    body = (await client.get(URL)).json()
    assert [row['code'] for row in body] == ['gluten', 'nuts', 'lactose']
    assert set(body[0]) == {'id', 'code', 'name'}


async def test_list_is_public_and_may_be_empty(client):
    r = await client.get(URL)
    assert r.status_code == 200
    assert r.json() == []
