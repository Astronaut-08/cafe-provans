from fastapi import APIRouter, Depends, Query

from app.db.models.location import Location
from app.modules.locations.service import get_active_location
from app.modules.menu.schemas import MenuRead
from app.modules.menu.service import MenuService, get_menu_service

router = APIRouter(prefix='/locations/{location_id}/menu', tags=['Menu'])


@router.get('', response_model=MenuRead, summary='Меню закладу')
async def get_menu(
    location: Location = Depends(get_active_location),
    service: MenuService = Depends(get_menu_service),
    available_only: bool = Query(False, description='Сховати страви зі стоп-листа'),
    featured: bool = Query(False, description='Лише страви для головної сторінки'),
):
    return await service.get_menu(location.id, available_only=available_only, featured_only=featured)
