"""seed: безпечний для мережі закладів з однаковою назвою Provans."""
from sqlalchemy import func, select

from app.db.models.allergen import Allergen
from app.db.models.delivery_zone import DeliveryZone
from app.db.models.location import Location
from app.db.seed import DELIVERY_ZONES, seed_delivery_zones, seed_required
from tests.factories import make_location


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_seed_creates_the_first_location_with_default_zones_on_empty_db(db_session):
    location = await seed_required(db_session)

    assert location.name == 'Provans' and location.city is None
    zones = (await db_session.execute(
        select(DeliveryZone.code, DeliveryZone.min_order_amount).order_by(DeliveryZone.sort_order)
    )).all()
    assert [(code, int(amount)) for code, amount in zones] == [('green', 400), ('yellow', 600), ('red', 1000)]
    assert await count(db_session, Allergen) == 14


async def test_seed_is_idempotent(db_session):
    first = await seed_required(db_session)
    second = await seed_required(db_session)

    assert first.id == second.id
    assert await count(db_session, Location) == 1
    assert await count(db_session, DeliveryZone) == len(DELIVERY_ZONES)


async def test_seed_does_not_fail_when_admin_has_added_more_locations_named_provans(db_session):
    # раніше заклад шукали за назвою: кілька однойменних закладів валили seed (MultipleResultsFound)
    first = await make_location(db_session, 'Provans', city='Болехів')
    await make_location(db_session, 'Provans', city="Велика Тур'я")
    await make_location(db_session, 'Provans', city='Третє')

    location = await seed_required(db_session)

    assert location.id == first.id                      # працює з першим
    assert await count(db_session, Location) == 3       # нових закладів не створює
    zones = (await db_session.scalars(select(DeliveryZone.location_id))).all()
    assert set(zones) == {first.id}                     # зони лише першому, чужі не чіпає


async def test_seed_keeps_admin_changes_in_existing_zones(db_session):
    location = await seed_required(db_session)
    green = await db_session.scalar(select(DeliveryZone).where(DeliveryZone.code == 'green'))
    green.min_order_amount = 555
    green.name = 'Моя зелена'
    await db_session.commit()

    await seed_required(db_session)
    await db_session.refresh(green)

    assert (green.name, int(green.min_order_amount)) == ('Моя зелена', 555)
    assert location.id == green.location_id


async def test_default_zones_can_be_created_for_any_new_location(db_session):
    await seed_required(db_session)
    new = await make_location(db_session, 'Provans', city="Велика Тур'я")

    await seed_delivery_zones(db_session, new.id)
    await seed_delivery_zones(db_session, new.id)       # повторно нічого не ламає

    codes = (await db_session.scalars(
        select(DeliveryZone.code).where(DeliveryZone.location_id == new.id).order_by(DeliveryZone.sort_order)
    )).all()
    assert codes == ['green', 'yellow', 'red']
    assert await count(db_session, DeliveryZone) == 2 * len(DELIVERY_ZONES)
