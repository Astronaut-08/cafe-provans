from datetime import datetime

from fastapi import APIRouter, Depends

from app.core.params import IdPath
from app.dependencies import get_now
from app.modules.locations.schemas import LocationPublic
from app.modules.locations.service import LocationService, get_location_service, to_public

router = APIRouter(prefix='/locations', tags=['Locations'])


@router.get('', response_model=list[LocationPublic], summary='Активні заклади')
async def list_locations(
    service: LocationService = Depends(get_location_service), now: datetime = Depends(get_now),
):
    return [to_public(location, now) for location in await service.list_active()]


@router.get('/{location_id}', response_model=LocationPublic, summary='Заклад за id')
async def get_location(
    location_id: IdPath,
    service: LocationService = Depends(get_location_service),
    now: datetime = Depends(get_now),
):
    return to_public(await service.get_active(location_id), now)
