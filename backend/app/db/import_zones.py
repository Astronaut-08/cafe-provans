"""Імпорт контурів зон доставки з карти Google My Maps. Запуск з папки backend:

    # 1. На карті: ⋮ біля назви → «Експортувати в KML/KMZ» → оберіть шар(и) з зонами → KML
    # 2. Покладіть файл у backend/ (щоб його бачив контейнер) і спершу зробіть пробний запуск:
    python -m app.db.import_zones --location-id 1 zones_bolekhiv.kml --dry-run
    # 3. Якщо звіт правильний, той самий запуск без --dry-run:
    python -m app.db.import_zones --location-id 1 zones_bolekhiv.kml

    # Багатокутник названо не «Зелена/Жовта/Червона зона» і колір не допомагає? Вкажіть вручну:
    python -m app.db.import_zones --location-id 1 zones.kml --assign "Центр=green" --assign "Околиці=red"

Кожна карта = один заклад, тож для двох закладів імпорт запускається двічі (з різними --location-id).
Скрипт ідемпотентний: повторний запуск просто замінює контури. Мінімальні суми й назви зон не чіпає.
Усе або нічого: помилка в будь-якому багатокутнику скасовує весь імпорт.
"""
import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.delivery_zone import DeliveryZone
from app.db.models.location import Location
from app.db.seed import DELIVERY_ZONES
from app.modules.delivery.kml import KmlError, build_zone_geometries, classify, parse_kml

_DEFAULTS = {code: (name, amount, order) for code, name, amount, order in DELIVERY_ZONES}


@dataclass
class ImportResult:
    updated: list[str] = field(default_factory=list)    # коди зон, чий контур замінено
    created: list[str] = field(default_factory=list)    # зони, яких у закладі ще не було
    untouched: list[str] = field(default_factory=list)  # зони закладу, для яких на карті контуру немає


async def apply_zones(
    session: AsyncSession, location_id: int, geometries: dict[str, dict], *, dry_run: bool = False,
) -> ImportResult:
    """Записує контури в зони закладу. Зони, яких ще немає, створює зі стандартними назвою й мінімумом
    (як у seed). У dry_run нічого не зберігає."""
    if await session.get(Location, location_id) is None:
        raise KmlError(f'Закладу з id {location_id} немає в базі (перевірте --location-id)')

    zones = {z.code: z for z in (await session.scalars(
        select(DeliveryZone).where(DeliveryZone.location_id == location_id)
    )).all()}
    result = ImportResult()

    for code, geometry in geometries.items():
        zone = zones.get(code)
        if zone is None:
            name, amount, order = _DEFAULTS[code]
            session.add(DeliveryZone(
                location_id=location_id, code=code, name=name, min_order_amount=amount,
                sort_order=order, polygon=geometry,
            ))
            result.created.append(code)
        else:
            zone.polygon = geometry
            result.updated.append(code)
    result.untouched = [code for code in zones if code not in geometries]

    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return result


def _report(parsed, assignments) -> list[str]:
    lines = [f'Знайдено багатокутників: {len(parsed.polygons)}']
    for a in assignments:
        label = a.code or '???'
        shape = a.polygon.geometry['type']
        lines.append(f'  «{a.polygon.name or "(без назви)"}»'
                     f' (шар: {a.polygon.folder or "-"}, колір: {a.polygon.color or "-"}, {shape})'
                     f' → {label} [{a.source}]')
    if parsed.ignored:
        lines.append(f'Проігноровано (не багатокутники): {", ".join(parsed.ignored)}')
    return lines


async def run(location_id: int, path: Path, overrides: dict[str, str], dry_run: bool) -> int:
    from app.db.session import SessionLocal, engine

    try:
        if not path.is_file():
            raise KmlError(f'Файл не знайдено: {path}. Покладіть його в папку backend/, щоб його бачив контейнер, '
                           f'і вкажіть шлях відносно неї.')
        parsed = parse_kml(path.read_bytes())
        if not parsed.polygons:
            raise KmlError('У файлі немає жодного багатокутника. Зони треба малювати інструментом «Намалювати лінію → '
                           'Додати лінію чи форму» і замкнути контур; точки й лінії не підходять.')
        assignments = classify(parsed.polygons, overrides)
        print('\n'.join(_report(parsed, assignments)))
        geometries = build_zone_geometries(assignments)

        async with SessionLocal() as session:
            result = await apply_zones(session, location_id, geometries, dry_run=dry_run)
    except (KmlError, OSError) as exc:
        print(f'ПОМИЛКА: {exc}', file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    if result.updated:
        print(f'Контур {"буде замінено" if dry_run else "замінено"}: {", ".join(result.updated)}')
    if result.created:
        created = ', '.join(f'{code} (від {int(_DEFAULTS[code][1])} грн)' for code in result.created)
        print(f'Зони {"буде створено" if dry_run else "створено"} зі стандартною мінімальною сумою: {created}')
    if result.untouched:
        print(f'Контуру на карті немає, зони лишились без змін: {", ".join(result.untouched)}')
    print('Пробний запуск: нічого не збережено.' if dry_run else 'Готово.')
    return 0


def _parse_assign(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        name, sep, code = value.rpartition('=')
        if not sep or not name.strip():
            raise SystemExit(f'--assign очікує формат "Назва=green", а отримано {value!r}')
        overrides[name.strip()] = code.strip().lower()
    return overrides


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Імпорт контурів зон доставки з KML/KMZ (Google My Maps)')
    parser.add_argument('kml', type=Path, help='файл .kml або .kmz, експортований з Google My Maps')
    parser.add_argument('--location-id', type=int, required=True, help='id закладу, до якого належить ця карта')
    parser.add_argument('--assign', action='append', default=[], metavar='НАЗВА=ЗОНА',
                        help='вручну призначити багатокутник зоні (green, yellow, red); можна кілька разів')
    parser.add_argument('--dry-run', action='store_true', help='лише показати, що буде зроблено, нічого не зберігати')
    args = parser.parse_args(argv)
    return asyncio.run(run(args.location_id, args.kml, _parse_assign(args.assign), args.dry_run))


if __name__ == '__main__':
    sys.exit(main())
