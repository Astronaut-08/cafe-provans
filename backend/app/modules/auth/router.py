"""HTTP-шар входу: розбір запиту й виклик сервісу. Вся логіка в service.py.

Потік роботи клієнта (фронтенду):
1. POST /auth/login -> access_token (короткий) + refresh_token (довгий). access іде в кожен запит
   заголовком `Authorization: Bearer <access_token>`.
2. Відповідь 401 з code=token_expired: POST /auth/refresh з refresh_token -> нова пара токенів
   (старий refresh більше не діє, зберегти треба новий).
3. Якщо у відповіді must_change_password=true: показати форму зміни пароля (POST /auth/change-password),
   до цього решта API відповідає 403 password_change_required.
4. POST /auth/logout з refresh_token завершує вхід.
Адмін, що забув пароль: POST /auth/forgot-password -> код на email -> POST /auth/reset-password.
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from app.db.models.user import User
from app.dependencies import get_current_user_any, get_now
from app.modules.auth.otp_sender import OtpSender, deliver_otp, get_otp_sender
from app.modules.auth.schemas import (
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, RefreshRequest,
    ResetPasswordRequest, TokenResponse,
)
from app.modules.auth.service import AuthService, get_auth_service
from app.modules.users.schemas import UserRead

router = APIRouter(prefix='/auth', tags=['Auth'])


@router.post('/login', response_model=TokenResponse)
async def login(data: LoginRequest, now: datetime = Depends(get_now), service: AuthService = Depends(get_auth_service)):
    return await service.login(data.login, data.password, now)


@router.post('/refresh', response_model=TokenResponse)
async def refresh(
    data: RefreshRequest, now: datetime = Depends(get_now), service: AuthService = Depends(get_auth_service),
):
    return await service.refresh(data.refresh_token, now)


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    data: RefreshRequest, now: datetime = Depends(get_now), service: AuthService = Depends(get_auth_service),
):
    await service.logout(data.refresh_token, now)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# get_current_user_any, а не get_current_user: з тимчасовим паролем потрібно мати змогу побачити себе
# й змінити пароль, решта API для такого користувача закрита
@router.get('/me', response_model=UserRead)
async def me(user: User = Depends(get_current_user_any)):
    return user


@router.post('/change-password', response_model=TokenResponse)
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user_any),
    now: datetime = Depends(get_now),
    service: AuthService = Depends(get_auth_service),
):
    return await service.change_password(user, data.current_password, data.new_password, now)


@router.post('/forgot-password', response_model=ForgotPasswordResponse, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    data: ForgotPasswordRequest,
    background: BackgroundTasks,
    now: datetime = Depends(get_now),
    service: AuthService = Depends(get_auth_service),
    sender: OtpSender = Depends(get_otp_sender),
):
    message = await service.forgot_password(data.login, now)
    if message is not None:
        # Лист надсилається ПІСЛЯ відповіді: повільний SMTP не впливає на час відповіді (за ним не вгадати,
        # чи існує акаунт), а збій пошти не перетворюється на помилку для клієнта
        background.add_task(deliver_otp, sender, message)
    return ForgotPasswordResponse()


@router.post('/reset-password', status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    data: ResetPasswordRequest, now: datetime = Depends(get_now), service: AuthService = Depends(get_auth_service),
):
    await service.reset_password(data.login, data.code, data.new_password, now)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
