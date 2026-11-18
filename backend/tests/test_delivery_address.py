"""Доставка за адресою: адміністратор вносить «ціле місто» або перелік вулиць у зоні, гість перевіряє свою адресу."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models.delivery_zone_area import DeliveryZoneArea
from tests.factories import make_area, make_location, make_zone, square

GREEN, YELLOW, RED = 'green', 'yellow', 'red'


def base(location) -> str:
    return f'/api/v1/locations/{location.id}/delivery'


async def check(client, location, city, street=None, **extra):
    body = {'city': city, **({'street': street} if street is not None else {}), **extra}
    return await client.post(f'{base(location)}/check-address', json=body)


async def zone_of(client, location, city, street=None):
    """Код зони або причина відмови: так тести читаються як таблиця «адреса → результат»."""
    r = await check(client, location, city, street)
    assert r.status_code == 200, r.text
    body = r.json()
    return body['zone']['code'] if body['deliverable'] else f"-{body['reason']}"


@pytest.fixture
async def location(db_session):
    return await make_location(db_session, 'Provans', city='Болехів')


@pytest.fixture
async def zones(db_session, location):
    return {
        GREEN: await make_zone(db_session, location, GREEN, minimum='400', sort_order=1),
        YELLOW: await make_zone(db_session, location, YELLOW, minimum='600', sort_order=2),
        RED: await make_zone(db_session, location, RED, minimum='1000', sort_order=3),
    }


@pytest.fixture
async def map_setup(db_session, location, zones):
    """Болехів: «Шевченка» і «Франка» зелені, решта міста жовта; Велика Тур'я й Нове Село повністю червоні."""
    await make_area(db_session, zones[GREEN], 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[GREEN], 'Болехів', 'вул. Франка')
    await make_area(db_session, zones[YELLOW], 'Болехів')
    await make_area(db_session, zones[RED], "Велика Тур'я")
    await make_area(db_session, zones[RED], 'Нове Село')
    return zones


# ---------- сценарії власника ----------

async def test_whole_city_in_a_zone_does_not_depend_on_the_street(client, location, map_setup):
    assert await zone_of(client, location, "Велика Тур'я") == RED
    assert await zone_of(client, location, "Велика Тур'я", 'вул. Будь-яка') == RED
    assert await zone_of(client, location, 'Нове Село', 'Центральна') == RED


async def test_street_listed_in_a_zone_gets_that_zone(client, location, map_setup):
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == GREEN
    assert await zone_of(client, location, 'Болехів', 'вул. Франка') == GREEN


async def test_street_wins_over_whole_city_and_the_rest_of_city_keeps_its_zone(client, location, map_setup):
    # Болехів цілком жовтий, але Шевченка й Франка зелені
    assert await zone_of(client, location, 'Болехів', 'вул. Дрогобицька') == YELLOW
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == GREEN


async def test_city_only_partly_covered_gives_pickup_for_unlisted_streets(client, db_session, location, zones):
    # жовта зона: лише перелік вулиць, «усього міста» немає
    await make_area(db_session, zones[YELLOW], 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[YELLOW], 'Болехів', 'вул. Франка')

    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == YELLOW
    assert await zone_of(client, location, 'Болехів', 'вул. Незаймана') == '-outside_zones'


async def test_unknown_city_is_pickup_only(client, location, map_setup):
    assert await zone_of(client, location, 'Київ', 'вул. Шевченка') == '-outside_zones'


async def test_result_carries_zone_name_minimum_and_free_delivery(client, location, map_setup):
    body = (await check(client, location, 'Болехів', 'вул. Шевченка')).json()
    assert body == {
        'deliverable': True,
        'zone': {'code': 'green', 'name': 'Green', 'min_order_amount': 400.0},
        'delivery_price': 0.0,
        'reason': None,
    }


# ---------- без вулиці ----------

async def test_city_without_street_when_whole_city_is_one_zone(client, location, map_setup):
    assert await zone_of(client, location, "Велика Тур'я") == RED
    assert await zone_of(client, location, 'Болехів') == YELLOW   # є запис «ціле місто»: відповідь однозначна


async def test_city_without_street_when_only_streets_are_listed_asks_for_street(client, db_session, location, zones):
    await make_area(db_session, zones[YELLOW], 'Болехів', 'вул. Шевченка')
    assert await zone_of(client, location, 'Болехів') == '-street_required'
    assert await zone_of(client, location, 'Болехів', '   ') == '-street_required'
    assert await zone_of(client, location, 'Болехів', '№ 5') == '-street_required'   # самий номер це не вулиця


# ---------- написання ----------

@pytest.mark.parametrize('city, street', [
    ('болехів', 'вул. шевченка'),
    ('БОЛЕХІВ', 'ВУЛИЦЯ ШЕВЧЕНКА'),
    ('м. Болехів', 'Шевченка вулиця'),
    ('  Болехів  ', '  вул. Шевченка, 5  '),
    ('Болехів', 'вул. Шевченка буд. 12/3'),
    ('Болехів', 'вул. Шевченка №7'),
])
async def test_spelling_variants_find_the_same_street(client, location, map_setup, city, street):
    assert await zone_of(client, location, city, street) == GREEN


@pytest.mark.parametrize('city', ["Велика Тур'я", 'Велика Турʼя', 'Велика Тур’я', 'Велика Туря', 'с. Велика Тур`я'])
async def test_apostrophe_in_any_form_finds_the_city(client, location, map_setup, city):
    assert await zone_of(client, location, city) == RED


async def test_admin_may_type_the_list_in_any_style_too(client, db_session, location, zones):
    await make_area(db_session, zones[GREEN], 'м. БОЛЕХІВ', 'Шевченка вулиця')
    assert await zone_of(client, location, 'Болехів', 'вул. шевченка') == GREEN


# ---------- вулиця / провулок із однаковою назвою ----------

@pytest.fixture
async def twin_streets(db_session, location, zones):
    await make_area(db_session, zones[GREEN], 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[RED], 'Болехів', 'пров. Шевченка')
    return zones


async def test_street_and_alley_with_the_same_name_keep_their_own_zones(client, location, twin_streets):
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == GREEN
    assert await zone_of(client, location, 'Болехів', 'пров. Шевченка') == RED
    assert await zone_of(client, location, 'Болехів', 'провулок Шевченка, 3') == RED


async def test_street_without_type_that_exists_in_different_zones_is_ambiguous(client, location, twin_streets):
    # обирати за гостя вулицю чи провулок не можна: він платить різний мінімум
    assert await zone_of(client, location, 'Болехів', 'Шевченка') == '-ambiguous_street'


async def test_street_without_type_is_fine_when_every_candidate_is_in_the_same_zone(client, db_session, location, zones):
    await make_area(db_session, zones[GREEN], 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[GREEN], 'Болехів', 'пров. Шевченка')
    assert await zone_of(client, location, 'Болехів', 'Шевченка') == GREEN


async def test_admin_entry_without_type_matches_a_guest_who_gave_one(client, db_session, location, zones):
    await make_area(db_session, zones[YELLOW], 'Болехів', 'Шевченка')
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == YELLOW
    assert await zone_of(client, location, 'Болехів', 'пров. Шевченка') == YELLOW
    assert await zone_of(client, location, 'Болехів', 'Шевченка') == YELLOW


async def test_alley_of_another_name_is_not_confused(client, location, twin_streets):
    assert await zone_of(client, location, 'Болехів', 'вул. Франка') == '-outside_zones'


# ---------- ізоляція ----------

async def test_location_without_any_areas_is_not_configured(client, location, zones):
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == '-not_configured'


async def test_polygons_do_not_count_for_address_check(client, db_session, location):
    # контури лише для карти: без списку адрес перевірка за адресою не налаштована
    await make_zone(db_session, location, GREEN, polygon=square(23.8, 49.0, 23.9, 49.1))
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == '-not_configured'


async def test_areas_of_inactive_zone_are_ignored(client, db_session, location):
    inactive = await make_zone(db_session, location, GREEN, active=False, sort_order=1)
    await make_area(db_session, inactive, 'Болехів')
    yellow = await make_zone(db_session, location, YELLOW, minimum='600', sort_order=2)
    await make_area(db_session, yellow, 'Болехів', 'вул. Франка')

    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == '-outside_zones'
    assert await zone_of(client, location, 'Болехів', 'вул. Франка') == YELLOW


async def test_areas_of_another_location_do_not_apply(client, db_session, location, zones):
    other = await make_location(db_session, 'Provans', city="Велика Тур'я")
    other_zone = await make_zone(db_session, other, GREEN, sort_order=1)
    await make_area(db_session, other_zone, 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[YELLOW], 'Болехів', 'вул. Франка')

    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == '-outside_zones'
    assert await zone_of(client, other, 'Болехів', 'вул. Шевченка') == GREEN


async def test_same_address_listed_twice_gives_the_cheapest_zone(client, db_session, location, zones):
    # написання різні, тож UNIQUE їх пропустив, але після нормалізації це одна й та сама вулиця одного типу.
    # Червону зону створено ПЕРШОЮ за id, тому виграє зелена лише завдяки порядку за sort_order
    await make_area(db_session, zones[RED], 'Болехів', 'вул. Шевченка')
    await make_area(db_session, zones[GREEN], 'Болехів', 'ВУЛ Шевченка')
    assert await zone_of(client, location, 'Болехів', 'вул. Шевченка') == GREEN


@pytest.mark.parametrize('listed, asked', [
    ('Нове', 'Нове Село'),                 # у списку коротша назва іншого населеного пункту
    ('Нове Село', 'Нове'),
    ("Тур'я", "Велика Тур'я"),             # сусідні села з однаковим «хвостом»
    ("Велика Тур'я", "Тур'я"),
])
async def test_city_must_match_entirely_not_as_a_part_of_another_name(client, db_session, location, zones, listed, asked):
    await make_area(db_session, zones[YELLOW], listed)
    assert await zone_of(client, location, asked) == '-outside_zones'


# ---------- вхідні дані ----------

@pytest.mark.parametrize('body', [
    {},
    {'street': 'вул. Шевченка'},
    {'city': ''},
    {'city': '   '},
    {'city': 'x' * 101},
    {'city': 'Болехів', 'street': 'x' * 151},
    {'city': 'Болехів', 'house': '5'},
    {'city': 5},
])
async def test_invalid_body_is_422(client, location, body):
    r = await client.post(f'{base(location)}/check-address', json=body)
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'validation_error'


@pytest.mark.parametrize('city', ['.', ' . ', 'м.', '-'])
async def test_city_without_letters_is_rejected_with_clear_message(client, location, city):
    r = await check(client, location, city)
    assert r.status_code == 422
    assert r.json()['error']['message'] == 'Вкажіть місто'


async def test_street_may_be_null_or_absent(client, location, map_setup):
    assert (await client.post(f'{base(location)}/check-address', json={'city': 'Болехів', 'street': None})).status_code == 200
    assert (await client.post(f'{base(location)}/check-address', json={'city': 'Болехів'})).status_code == 200


async def test_check_address_is_post_only(client, location):
    assert (await client.get(f'{base(location)}/check-address?city=Болехів')).status_code == 405


async def test_unknown_or_inactive_location_is_404(client, db_session):
    hidden = await make_location(db_session, active=False)
    for location_id in (999, hidden.id):
        r = await client.post(f'/api/v1/locations/{location_id}/delivery/check-address', json={'city': 'Болехів'})
        assert r.status_code == 404


async def test_huge_location_id_is_422(client):
    r = await client.post('/api/v1/locations/99999999999/delivery/check-address', json={'city': 'Болехів'})
    assert r.status_code == 422


# ---------- GET /delivery: що бачить сайт ----------

async def test_info_lists_areas_per_zone_and_map_url(client, db_session, zones):
    location = await make_location(db_session, map_url='https://www.google.com/maps/d/embed?mid=abc')
    green = await make_zone(db_session, location, GREEN, sort_order=1)
    yellow = await make_zone(db_session, location, YELLOW, minimum='600', sort_order=2)
    await make_area(db_session, green, 'Болехів', 'вул. Франка')
    await make_area(db_session, green, 'Болехів', 'вул. Шевченка')
    await make_area(db_session, yellow, 'Болехів')
    await make_area(db_session, yellow, "Велика Тур'я")

    body = (await client.get(base(location))).json()

    assert body['map_url'] == 'https://www.google.com/maps/d/embed?mid=abc'
    by_code = {z['code']: z['areas'] for z in body['zones']}
    assert by_code[GREEN] == [{'city': 'Болехів', 'street': 'вул. Франка'}, {'city': 'Болехів', 'street': 'вул. Шевченка'}]
    # «ціле місто» віддається як street = null, а не як порожній рядок із БД
    assert {'city': 'Болехів', 'street': None} in by_code[YELLOW]
    assert {'city': "Велика Тур'я", 'street': None} in by_code[YELLOW]


async def test_info_without_map_and_without_areas(client, db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, GREEN)
    body = (await client.get(base(location))).json()
    assert body['map_url'] is None
    assert body['zones'][0]['areas'] == []


async def test_info_hides_areas_of_inactive_zones_and_of_other_locations(client, db_session, location, zones):
    other = await make_location(db_session, city='Інше')
    other_zone = await make_zone(db_session, other, GREEN)
    inactive = await make_zone(db_session, location, 'blue', active=False, sort_order=9)
    await make_area(db_session, other_zone, 'Чуже')
    await make_area(db_session, inactive, 'Прихована')
    await make_area(db_session, zones[GREEN], 'Болехів')

    body = (await client.get(base(location))).json()

    cities = {a['city'] for z in body['zones'] for a in z['areas']}
    assert cities == {'Болехів'}


async def test_public_location_shows_city_but_not_map_url(client, db_session):
    location = await make_location(db_session, 'Provans', city='Болехів', map_url='https://example.com/m')
    body = (await client.get(f'/api/v1/locations/{location.id}')).json()
    assert body['city'] == 'Болехів'
    assert 'delivery_map_url' not in body   # карта віддається разом із зонами доставки


# ---------- обмеження в БД ----------

async def test_database_rejects_area_of_zone_from_another_location(db_session, location, zones):
    other = await make_location(db_session, city='Інше')
    with pytest.raises(IntegrityError, match='fk_delivery_zone_areas_zone_location'):
        # зона Болехова, а заклад чужий: адреса не може потрапити в зону чужого закладу
        db_session.add(DeliveryZoneArea(location_id=other.id, zone_id=zones[GREEN].id, city='X', street=''))
        await db_session.flush()


async def test_database_rejects_the_same_place_twice(db_session, location, zones):
    await make_area(db_session, zones[GREEN], 'Болехів')
    with pytest.raises(IntegrityError, match='uq_delivery_zone_areas_place'):
        await make_area(db_session, zones[YELLOW], 'Болехів')   # «ціле місто» вдруге, навіть в іншій зоні


@pytest.mark.parametrize('city, street, constraint', [
    ('', '', 'city_not_blank'),
    ('   ', '', 'city_not_blank'),
    ('Болехів', ' вул. Шевченка', 'street_trimmed'),
    ('Болехів', '   ', 'street_trimmed'),     # інакше після нормалізації це було б мовчки «ціле місто»
])
async def test_database_rejects_blank_city_and_untrimmed_street(db_session, location, zones, city, street, constraint):
    with pytest.raises(IntegrityError, match=constraint):
        await make_area(db_session, zones[GREEN], city, street)


async def test_deleting_a_zone_or_location_removes_its_areas(db_session, location, zones):
    await make_area(db_session, zones[GREEN], 'Болехів')
    await make_area(db_session, zones[YELLOW], 'Болехів', 'вул. Франка')

    async def count() -> int:
        return await db_session.scalar(select(func.count()).select_from(DeliveryZoneArea))

    await db_session.delete(zones[GREEN])
    await db_session.commit()
    assert await count() == 1
    await db_session.delete(location)
    await db_session.commit()
    assert await count() == 0
