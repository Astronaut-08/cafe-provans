"""Імпорт контурів зон у БД (app.db.import_zones) і його командний рядок."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.import_zones import apply_zones, main
from app.db.models.delivery_zone import DeliveryZone
from app.modules.delivery.kml import KmlError, build_zone_geometries, classify, parse_kml
from tests.factories import make_location, make_zone, square
from tests.kml_samples import GREEN_BOX, folder, kml, placemark, polygon, three_zones_kml


def geometries(data: bytes | None = None) -> dict[str, dict]:
    return build_zone_geometries(classify(parse_kml(data or three_zones_kml()).polygons))


async def zones_of(db, location) -> dict[str, DeliveryZone]:
    rows = await db.scalars(select(DeliveryZone).where(DeliveryZone.location_id == location.id))
    return {z.code: z for z in rows}


# ---------- запис у БД ----------

async def test_updates_polygons_but_keeps_name_and_minimum(db_session):
    location = await make_location(db_session)
    await make_zone(db_session, location, 'green', name='Моя зелена', minimum='450', sort_order=1)

    result = await apply_zones(db_session, location.id, {'green': geometries()['green']})

    zone = (await zones_of(db_session, location))['green']
    assert result.updated == ['green'] and result.created == []
    assert zone.polygon['type'] == 'Polygon'
    assert (zone.name, zone.min_order_amount) == ('Моя зелена', Decimal('450.00'))   # бізнес-налаштування не чіпаємо


async def test_missing_zones_are_created_with_seed_defaults(db_session):
    location = await make_location(db_session)   # заклад без зон: як другий заклад після seed

    result = await apply_zones(db_session, location.id, geometries())

    assert sorted(result.created) == ['green', 'red', 'yellow'] and result.updated == []
    zones = await zones_of(db_session, location)
    assert {c: (z.name, z.min_order_amount, z.sort_order) for c, z in zones.items()} == {
        'green': ('Зелена зона', Decimal('400.00'), 1),
        'yellow': ('Жовта зона', Decimal('600.00'), 2),
        'red': ('Червона зона', Decimal('1000.00'), 3),
    }
    assert all(z.polygon for z in zones.values())


async def test_zone_absent_on_the_map_is_left_untouched_not_wiped(db_session):
    location = await make_location(db_session)
    old = square(1, 1, 2, 2)
    await make_zone(db_session, location, 'red', polygon=old, minimum='1000', sort_order=3)

    result = await apply_zones(db_session, location.id, {'green': geometries()['green']})

    assert result.untouched == ['red'] and result.created == ['green']
    assert (await zones_of(db_session, location))['red'].polygon == old


async def test_import_is_idempotent(db_session):
    location = await make_location(db_session)
    await apply_zones(db_session, location.id, geometries())
    result = await apply_zones(db_session, location.id, geometries())

    assert sorted(result.updated) == ['green', 'red', 'yellow'] and result.created == []
    count = await db_session.scalar(select(func.count()).select_from(DeliveryZone).where(DeliveryZone.location_id == location.id))
    assert count == 3


async def test_reimport_replaces_the_old_polygon(db_session):
    location = await make_location(db_session)
    await apply_zones(db_session, location.id, {'green': square(0, 0, 1, 1)})
    await apply_zones(db_session, location.id, {'green': square(10, 10, 11, 11)})
    assert (await zones_of(db_session, location))['green'].polygon == square(10, 10, 11, 11)


def fresh_session(connection):
    """Окрема сесія, як у справжньому запуску: збережене лише те, що сам apply_zones закомітив."""
    from sqlalchemy.ext.asyncio import AsyncSession
    return AsyncSession(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False)


async def test_import_is_committed_by_apply_zones_itself(db_connection, db_session):
    location = await make_location(db_session)
    async with fresh_session(db_connection) as session:
        await apply_zones(session, location.id, geometries())
    # сесію закрито без власного commit: якщо apply_zones забув commit, зони зникли б
    assert set(await zones_of(db_session, location)) == {'green', 'yellow', 'red'}


async def test_dry_run_in_a_separate_session_leaves_no_trace(db_connection, db_session):
    location = await make_location(db_session)
    async with fresh_session(db_connection) as session:
        await apply_zones(session, location.id, geometries(), dry_run=True)
    assert await zones_of(db_session, location) == {}


async def test_unknown_location_is_rejected(db_session):
    with pytest.raises(KmlError, match='немає в базі'):
        await apply_zones(db_session, 999999, geometries())


async def test_dry_run_saves_nothing(db_session):
    empty = await make_location(db_session, 'Без зон')
    with_zone = await make_location(db_session, 'З зоною')
    await make_zone(db_session, with_zone, 'green', polygon=None)
    # rollback у dry-run робить усі обʼєкти сесії «застарілими», тож id беремо заздалегідь
    empty_id, with_zone_id = empty.id, with_zone.id

    r1 = await apply_zones(db_session, empty_id, geometries(), dry_run=True)
    r2 = await apply_zones(db_session, with_zone_id, {'green': geometries()['green']}, dry_run=True)

    assert sorted(r1.created) == ['green', 'red', 'yellow'] and r2.updated == ['green']   # звіт показує, що БУЛО Б
    assert await zones_of(db_session, SimpleNamespace(id=empty_id)) == {}
    assert (await zones_of(db_session, SimpleNamespace(id=with_zone_id)))['green'].polygon is None


async def test_locations_are_independent(db_session):
    bolekhiv = await make_location(db_session, 'Болехів')
    turia = await make_location(db_session, 'Велика Тура')
    await apply_zones(db_session, bolekhiv.id, geometries())
    await apply_zones(db_session, turia.id, {'green': square(1, 1, 2, 2)})

    assert (await zones_of(db_session, bolekhiv))['green'].polygon['coordinates'][0][0] == [23.84, 49.04]
    assert (await zones_of(db_session, turia))['green'].polygon == square(1, 1, 2, 2)
    assert set(await zones_of(db_session, turia)) == {'green'}


async def test_imported_map_drives_the_public_check_endpoint(client, db_session):
    """Весь шлях: KML → імпорт → POST /delivery/check з реальними координатами Болехова."""
    location = await make_location(db_session)
    await apply_zones(db_session, location.id, geometries())
    url = f'/api/v1/locations/{location.id}/delivery/check'

    async def zone_at(lat, lng):
        return (await client.post(url, json={'lat': lat, 'lng': lng})).json()

    center = await zone_at(49.05, 23.85)
    assert (center['zone']['code'], center['zone']['min_order_amount']) == ('green', 400.0)
    assert (await zone_at(49.035, 23.85))['zone']['code'] == 'yellow'
    assert (await zone_at(49.01, 23.85))['zone']['min_order_amount'] == 1000.0
    far = await zone_at(50.0, 24.0)
    assert (far['deliverable'], far['reason']) == (False, 'outside_zones')


# ---------- командний рядок (помилки, що не доходять до запису) ----------

def run_cli(tmp_path, content: bytes | None, *args, name='zones.kml'):
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    return main([str(path), *args])


def test_cli_missing_file(tmp_path, capsys):
    assert run_cli(tmp_path, None, '--location-id', '1') == 1
    err = capsys.readouterr().err
    assert 'Файл не знайдено' in err and 'backend' in err


def test_cli_file_without_polygons(tmp_path, capsys):
    assert run_cli(tmp_path, kml(placemark('Піцерія', '<Point><coordinates>1,2,0</coordinates></Point>')), '--location-id', '1') == 1
    assert 'немає жодного багатокутника' in capsys.readouterr().err


def test_cli_garbage_file(tmp_path, capsys):
    assert run_cli(tmp_path, b'<<<not xml', '--location-id', '1') == 1
    assert 'ПОМИЛКА' in capsys.readouterr().err


def test_cli_unassigned_polygon_shows_report_and_how_to_fix(tmp_path, capsys):
    data = kml(placemark('Центр', polygon(*GREEN_BOX)))
    assert run_cli(tmp_path, data, '--location-id', '1') == 1
    captured = capsys.readouterr()
    assert '«Центр»' in captured.out and '???' in captured.out       # звіт показано до помилки
    assert '--assign' in captured.err


def test_cli_manual_assignment_gets_past_classification_to_the_database_check(tmp_path, capsys):
    # заклад 999999 не існує: помилка саме про заклад, отже --assign спрацював і імпорт дійшов до БД
    data = kml(placemark('Центр', polygon(*GREEN_BOX)))
    assert run_cli(tmp_path, data, '--location-id', '999999', '--assign', 'Центр=green', '--dry-run') == 1
    captured = capsys.readouterr()
    assert 'вручну' in captured.out and 'немає в базі' in captured.err


def test_cli_invalid_assign_code(tmp_path, capsys):
    data = kml(placemark('Центр', polygon(*GREEN_BOX)))
    assert run_cli(tmp_path, data, '--location-id', '1', '--assign', 'Центр=blue') == 1
    assert 'green, yellow, red' in capsys.readouterr().err


def test_cli_assign_with_wrong_format_exits(tmp_path):
    with pytest.raises(SystemExit, match='Назва=green'):
        run_cli(tmp_path, three_zones_kml(), '--location-id', '1', '--assign', 'без-дорівнює')


def test_cli_requires_location_id(tmp_path):
    with pytest.raises(SystemExit):
        run_cli(tmp_path, three_zones_kml())


def test_cli_report_lists_polygons_with_source(tmp_path, capsys):
    data = kml(folder('Шар', placemark('Зелена зона', polygon(*GREEN_BOX))))
    run_cli(tmp_path, data, '--location-id', '999999', '--dry-run')
    out = capsys.readouterr().out
    assert 'Знайдено багатокутників: 1' in out and '→ green [за назвою]' in out
