from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.db.models.location import Location
from app.dependencies import get_now
from app.modules.locations.service import get_active_location
from app.modules.promotions.schemas import PromotionRead
from app.modules.promotions.service import PromotionService, get_promotion_service

router = APIRouter(prefix='/locations/{location_id}/promotions', tags=['Promotions'])


@router.get('', response_model=list[PromotionRead], summary='Акції, що діють у закладі зараз')
async def list_promotions(
    location: Location = Depends(get_active_location),
    service: PromotionService = Depends(get_promotion_service),
    now: datetime = Depends(get_now),
    featured: bool = Query(False, description='Лише акції для головної сторінки'),
):
    return await service.list_active(location, now, featured_only=featured)
