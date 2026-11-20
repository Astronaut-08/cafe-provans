"""Керування стравами. Усе тільки для адміна (роль перевіряється на весь роутер одразу).
Стоп-лист для офіціанта лежить поруч із меню закладу: PATCH /locations/{id}/menu/{dish_id}/availability.
"""
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.core.params import IdPath
from app.db.enums import UserRole
from app.dependencies import require_roles
from app.modules.dishes.schemas import DishAdminRead, DishCreate, DishLocationRead, DishLocationWrite, DishUpdate
from app.modules.dishes.service import DishService, get_dish_service

router = APIRouter(prefix='/dishes', tags=['Dishes (admin)'], dependencies=[Depends(require_roles(UserRole.admin))])


@router.get('', response_model=list[DishAdminRead], summary='Усі страви (робочий список адміна)')
async def list_dishes(
    category_id: int | None = Query(None, ge=1, le=2_147_483_647),
    location_id: int | None = Query(None, ge=1, le=2_147_483_647, description='Лише страви, що продаються в закладі'),
    is_available: bool | None = Query(None, description='Фільтр за глобальною ознакою «в продажу»'),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: DishService = Depends(get_dish_service),
):
    return await service.list(
        category_id=category_id, location_id=location_id, is_available=is_available, limit=limit, offset=offset,
    )


@router.post('', response_model=DishAdminRead, status_code=status.HTTP_201_CREATED, summary='Створити страву')
async def create_dish(data: DishCreate, service: DishService = Depends(get_dish_service)):
    return await service.create(data)


@router.get('/{dish_id}', response_model=DishAdminRead)
async def get_dish(dish_id: IdPath, service: DishService = Depends(get_dish_service)):
    return await service.get(dish_id)


@router.patch('/{dish_id}', response_model=DishAdminRead, summary='Змінити страву (лише передані поля)')
async def update_dish(dish_id: IdPath, data: DishUpdate, service: DishService = Depends(get_dish_service)):
    return await service.update(dish_id, data)


@router.delete(
    '/{dish_id}', status_code=status.HTTP_204_NO_CONTENT,
    summary='Видалити страву (409, якщо вона є в замовленнях або акціях)',
)
async def delete_dish(dish_id: IdPath, service: DishService = Depends(get_dish_service)):
    await service.delete(dish_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    '/{dish_id}/locations/{location_id}', response_model=DishLocationRead,
    summary='Додати страву в заклад або змінити її там (власна ціна закладу, доступність)',
)
async def put_dish_location(
    dish_id: IdPath, location_id: IdPath, data: DishLocationWrite,
    service: DishService = Depends(get_dish_service),
):
    return await service.put_location(dish_id, location_id, data)


@router.delete(
    '/{dish_id}/locations/{location_id}', status_code=status.HTTP_204_NO_CONTENT,
    summary='Прибрати страву з меню закладу',
)
async def remove_dish_location(
    dish_id: IdPath, location_id: IdPath, service: DishService = Depends(get_dish_service),
):
    await service.remove_location(dish_id, location_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/{dish_id}/image', response_model=DishAdminRead,
    summary='Завантажити фото страви (JPEG, PNG або WebP до 5 МБ; заміняє попереднє)',
)
async def upload_dish_image(
    dish_id: IdPath,
    file: UploadFile = File(..., description='Файл зображення'),
    service: DishService = Depends(get_dish_service),
):
    return await service.set_image(dish_id, file)


@router.delete('/{dish_id}/image', response_model=DishAdminRead, summary='Прибрати фото страви')
async def delete_dish_image(dish_id: IdPath, service: DishService = Depends(get_dish_service)):
    return await service.remove_image(dish_id)
