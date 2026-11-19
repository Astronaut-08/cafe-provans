"""Керування персоналом. Усе лише для адміністратора (одна залежність на весь роутер).
Свої дані й зміна власного пароля: див. /auth/me та /auth/change-password."""
from datetime import datetime

from fastapi import APIRouter, Depends, status

from app.core.params import IdPath
from app.db.enums import UserRole
from app.db.models.user import User
from app.dependencies import get_current_user, get_now, require_roles
from app.modules.users.schemas import TemporaryPassword, UserCreate, UserRead, UserUpdate
from app.modules.users.service import UserService, get_user_service

router = APIRouter(prefix='/users', tags=['Users'], dependencies=[Depends(require_roles(UserRole.admin))])


@router.get('', response_model=list[UserRead])
async def list_users(
    role: UserRole | None = None,
    is_active: bool | None = None,
    location_id: int | None = None,
    service: UserService = Depends(get_user_service),
):
    return await service.list(role=role, is_active=is_active, location_id=location_id)


@router.post('', response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, service: UserService = Depends(get_user_service)):
    return await service.create(data)


@router.get('/{user_id}', response_model=UserRead)
async def get_user(user_id: IdPath, service: UserService = Depends(get_user_service)):
    return await service.get(user_id)


@router.patch('/{user_id}', response_model=UserRead)
async def update_user(
    user_id: IdPath, data: UserUpdate, now: datetime = Depends(get_now),
    service: UserService = Depends(get_user_service),
):
    return await service.update(user_id, data, now)


@router.post('/{user_id}/reset-password', response_model=TemporaryPassword)
async def reset_password(
    user_id: IdPath,
    actor: User = Depends(get_current_user),
    now: datetime = Depends(get_now),
    service: UserService = Depends(get_user_service),
):
    """Скидає пароль працівника. Старий пароль побачити неможливо; новий тимчасовий показується один раз,
    а працівник мусить замінити його при першому вході. Усі його поточні входи завершуються."""
    return TemporaryPassword(temporary_password=await service.reset_password(user_id, actor, now))
