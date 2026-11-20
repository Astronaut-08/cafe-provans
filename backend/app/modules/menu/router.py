from fastapi import APIRouter, Body, Depends, Query

from app.core.params import IdPath
from app.db.enums import UserRole
from app.db.models.location import Location
from app.db.models.user import User
from app.dependencies import get_current_user, require_roles
from app.modules.dishes.schemas import DishLocationRead
from app.modules.dishes.service import DishService, get_dish_service
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


@router.patch(
    '/{dish_id}/availability', response_model=DishLocationRead,
    dependencies=[Depends(require_roles(UserRole.waiter))],
    summary='Стоп-лист: страва є / закінчилась у цьому закладі',
)
async def set_dish_availability(
    location_id: IdPath,
    dish_id: IdPath,
    is_available: bool = Body(..., embed=True),
    actor: User = Depends(get_current_user),
    service: DishService = Depends(get_dish_service),
):
    """Офіціант (і адмін) позначає, що страва закінчилась або знову є. Офіціант лише у своєму закладі."""
    return await service.set_availability(actor, location_id, dish_id, is_available)
