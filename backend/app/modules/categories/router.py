"""HTTP-шар: розбір запиту, перевірка прав, виклик сервісу. Жодної бізнес-логіки.

Читання публічне (меню бачать усі гості). Зміна доступна лише адміну:
доки не реалізований вхід (Фаза 4), `require_roles` закриває ці ендпоінти (401).
"""
from fastapi import APIRouter, Depends, Response, status

from app.core.params import IdPath
from app.db.enums import UserRole
from app.dependencies import require_roles
from app.modules.categories.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.modules.categories.service import CategoryService, get_category_service

router = APIRouter(prefix='/categories', tags=['Categories'])

admin_only = Depends(require_roles(UserRole.admin))


@router.get('', response_model=list[CategoryRead])
async def list_categories(service: CategoryService = Depends(get_category_service)):
    return await service.list()


@router.get('/{category_id}', response_model=CategoryRead)
async def get_category(category_id: IdPath, service: CategoryService = Depends(get_category_service)):
    return await service.get(category_id)


@router.post('', response_model=CategoryRead, status_code=status.HTTP_201_CREATED, dependencies=[admin_only])
async def create_category(data: CategoryCreate, service: CategoryService = Depends(get_category_service)):
    return await service.create(data)


@router.patch('/{category_id}', response_model=CategoryRead, dependencies=[admin_only])
async def update_category(
    category_id: IdPath, data: CategoryUpdate, service: CategoryService = Depends(get_category_service),
):
    return await service.update(category_id, data)


@router.delete('/{category_id}', status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_only])
async def delete_category(category_id: IdPath, service: CategoryService = Depends(get_category_service)):
    await service.delete(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
