from datetime import datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.params import IdPath
from app.core.timewindow import in_time_window, to_local
from app.db.models.location import Location
from app.dependencies import get_db
from app.modules.locations.schemas import LocationPublic


def to_public(location: Location, now: datetime) -> LocationPublic:
    """ORM-заклад у публічну схему з обчисленим `is_open_now` (за місцевим часом закладу)."""
    public = LocationPublic.model_validate(location)
    if location.opening_time is not None and location.closing_time is not None:
        local_time = to_local(now, location.timezone).time()
        public.is_open_now = in_time_window(location.opening_time, location.closing_time, local_time)
    return public


class LocationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Location]:
        result = await self.session.scalars(select(Location).where(Location.is_active).order_by(Location.id))
        return list(result.all())

    async def get_active(self, location_id: int) -> Location:
        # неактивний заклад для публічного API не існує: 404, а не 403
        location = await self.session.scalar(
            select(Location).where(Location.id == location_id, Location.is_active)
        )
        if location is None:
            raise NotFoundError('Заклад не знайдено')
        return location


def get_location_service(session: AsyncSession = Depends(get_db)) -> LocationService:
    return LocationService(session)


async def get_active_location(
    location_id: IdPath, service: LocationService = Depends(get_location_service),
) -> Location:
    """Залежність для всіх маршрутів виду /locations/{location_id}/...: заклад має існувати й бути активним."""
    return await service.get_active(location_id)
