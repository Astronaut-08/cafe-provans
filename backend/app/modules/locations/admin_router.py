"""Керування закладами (лише адмін). Гість бачить заклади через публічний /locations (див. router.py):
там лише активні й без службових полів, а тут усі.

Заклад не видаляється, а вимикається (`is_active: false`): на нього посилаються працівники, замовлення, зони.
"""
from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.params import IdPath
from app.db.enums import UserRole
from app.dependencies import require_roles
from app.modules.locations.schemas import LocationCreate, LocationRead, LocationUpdate
from app.modules.locations.service import LocationService, get_location_service

router = APIRouter(
    prefix='/admin/locations', tags=['Locations (admin)'], dependencies=[Depends(require_roles(UserRole.admin))],
)


@router.get('', response_model=list[LocationRead], summary='Усі заклади, і неактивні також')
async def list_locations(service: LocationService = Depends(get_location_service)):
    return await service.list_all()


@router.post('', response_model=LocationRead, status_code=status.HTTP_201_CREATED, summary='Створити заклад')
async def create_location(data: LocationCreate, service: LocationService = Depends(get_location_service)):
    return await service.create(data)


@router.get('/{location_id}', response_model=LocationRead)
async def get_location(location_id: IdPath, service: LocationService = Depends(get_location_service)):
    return await service.get_any(location_id)


@router.patch('/{location_id}', response_model=LocationRead, summary='Змінити заклад (лише передані поля)')
async def update_location(
    location_id: IdPath, data: LocationUpdate, service: LocationService = Depends(get_location_service),
):
    return await service.update(location_id, data)


@router.post(
    '/{location_id}/image', response_model=LocationRead,
    summary='Завантажити фото закладу (JPEG, PNG або WebP до 5 МБ; заміняє попереднє)',
)
async def upload_location_image(
    location_id: IdPath,
    file: UploadFile = File(..., description='Файл зображення'),
    service: LocationService = Depends(get_location_service),
):
    return await service.set_image(location_id, file)


@router.delete('/{location_id}/image', response_model=LocationRead, summary='Прибрати фото закладу')
async def delete_location_image(location_id: IdPath, service: LocationService = Depends(get_location_service)):
    return await service.remove_image(location_id)
