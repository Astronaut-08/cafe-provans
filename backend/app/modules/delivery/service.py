from collections import defaultdict
from decimal import Decimal

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.db.models.delivery_zone import DeliveryZone
from app.db.models.delivery_zone_area import DeliveryZoneArea
from app.db.models.location import Location
from app.dependencies import get_db
from app.modules.delivery.geometry import geometry_contains
from app.modules.delivery.places import find_street, normalize_city, parse_street
from app.modules.delivery.schemas import AreaInfo, DeliveryCheck, DeliveryInfo, ZoneBrief, ZoneInfo

# Доставка безкоштовна. Умова одна: сума замовлення не менша за мінімум зони (green 400, yellow 600, red 1000).
DELIVERY_PRICE = Decimal('0')


def _delivered(zone) -> DeliveryCheck:
    return DeliveryCheck(
        deliverable=True,
        zone=ZoneBrief(code=zone.code, name=zone.name, min_order_amount=zone.min_order_amount),
        delivery_price=DELIVERY_PRICE,
    )


def _not_delivered(reason: str) -> DeliveryCheck:
    return DeliveryCheck(deliverable=False, zone=None, delivery_price=None, reason=reason)


class DeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_info(self, location: Location) -> DeliveryInfo:
        # контур (може бути великим) для списку не потрібен, беремо лише факт його наявності
        rows = await self.session.execute(
            select(
                DeliveryZone.id, DeliveryZone.code, DeliveryZone.name, DeliveryZone.min_order_amount,
                DeliveryZone.description, DeliveryZone.polygon.is_not(None).label('has_area'),
            )
            .where(DeliveryZone.location_id == location.id, DeliveryZone.is_active)
            .order_by(DeliveryZone.sort_order, DeliveryZone.id)
        )
        zones = rows.all()

        area_rows = await self.session.execute(
            select(DeliveryZoneArea.zone_id, DeliveryZoneArea.city, DeliveryZoneArea.street)
            .where(DeliveryZoneArea.location_id == location.id)
            .order_by(DeliveryZoneArea.city, DeliveryZoneArea.street)
        )
        areas: dict[int, list[AreaInfo]] = defaultdict(list)
        for zone_id, city, street in area_rows:
            areas[zone_id].append(AreaInfo(city=city, street=street or None))

        return DeliveryInfo(
            delivery_price=DELIVERY_PRICE,
            map_url=location.delivery_map_url,
            zones=[
                ZoneInfo(
                    code=z.code, name=z.name, min_order_amount=z.min_order_amount,
                    description=z.description, has_area=z.has_area, areas=areas.get(z.id, []),
                )
                for z in zones
            ],
        )

    async def check_address(self, location_id: int, city: str, street: str | None) -> DeliveryCheck:
        """У якій зоні адреса, за списком, який вніс адміністратор (ціле місто або перелік вулиць).

        Вулиця переважає над містом: якщо місто жовте, а вулиця Шевченка зелена, то Шевченка зелена.
        Якщо місто є лише переліком вулиць, а гість вказаної вулиці в переліку немає, то це самовивіз.
        """
        city_key = normalize_city(city)
        if not city_key:
            raise UnprocessableError('Вкажіть місто')

        rows = (await self.session.execute(
            select(
                DeliveryZoneArea.city, DeliveryZoneArea.street,
                DeliveryZone.id, DeliveryZone.code, DeliveryZone.name, DeliveryZone.min_order_amount,
            )
            .join(DeliveryZone, DeliveryZone.id == DeliveryZoneArea.zone_id)
            .where(DeliveryZoneArea.location_id == location_id, DeliveryZone.is_active)
            # від найближчої зони: якщо одна адреса випадково записана двічі, виграє вигідніша для гостя
            .order_by(DeliveryZone.sort_order, DeliveryZone.id)
        )).all()

        if not rows:
            return _not_delivered('not_configured')

        in_city = [row for row in rows if normalize_city(row.city) == city_key]
        whole_city = [row for row in in_city if parse_street(row.street) is None]
        streets = [(parsed, row) for row in in_city if (parsed := parse_street(row.street)) is not None]

        requested = parse_street(street)
        if requested is None:
            # вулицю не вказано: відповісти можна лише коли все місто в одній зоні
            if whole_city:
                return _delivered(whole_city[0])
            return _not_delivered('street_required' if streets else 'outside_zones')

        matches = find_street(requested, streets)
        if matches:
            zone_ids = {row.id for row in matches}
            if requested.kind is None and len(zone_ids) > 1:
                return _not_delivered('ambiguous_street')
            return _delivered(matches[0])
        if whole_city:
            return _delivered(whole_city[0])
        return _not_delivered('outside_zones')

    async def check(self, location_id: int, lat: float, lng: float) -> DeliveryCheck:
        """У якій зоні точка за контурами на карті (запасний спосіб; основний це check_address).
        Зони перебираємо від найближчої (sort_order): якщо контури вкладені (червона охоплює жовту, жовта зелену),
        виграє найвигідніша для гостя, тобто найменший мінімум."""
        zones = (await self.session.scalars(
            select(DeliveryZone)
            .where(DeliveryZone.location_id == location_id, DeliveryZone.is_active,
                   DeliveryZone.polygon.is_not(None))
            .order_by(DeliveryZone.sort_order, DeliveryZone.id)
        )).all()

        if not zones:
            return _not_delivered('not_configured')

        for zone in zones:
            if geometry_contains(zone.polygon, lng, lat):  # GeoJSON: [довгота, широта]
                return _delivered(zone)
        return _not_delivered('outside_zones')


def get_delivery_service(session: AsyncSession = Depends(get_db)) -> DeliveryService:
    return DeliveryService(session)
