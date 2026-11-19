from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.tokens import TokenError, decode_access_token
from app.db.enums import UserRole
from app.db.models.user import User
from app.db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    """Лише видає сесію. Транзакціями керують сервіси: метод сервісу, що щось пише,
    сам викликає `await session.commit()` у кінці. Читальні методи commit не викликають.
    Якщо запит завершився помилкою, незакомічене відкочується при закритті сесії.
    """
    async with SessionLocal() as session:
        yield session


def get_now() -> datetime:
    """Поточний момент (UTC). Окрема залежність, щоб логіку «зараз» (чи відкрито, чи діє акція)
    можна було тестувати з фіксованим часом через `dependency_overrides`."""
    return datetime.now(UTC)


# auto_error=False: відсутній токен обробляємо самі, щоб відповідь мала наш єдиний формат помилки.
# Схема Bearer також дає кнопку «Authorize» у /docs: туди вставляється access_token із відповіді /auth/login.
bearer_scheme = HTTPBearer(auto_error=False, description='access_token із відповіді POST /auth/login')

_WWW_AUTHENTICATE = {'WWW-Authenticate': 'Bearer'}


async def get_current_user_any(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
    now: datetime = Depends(get_now),
) -> User:
    """Користувач із access-токена, навіть якщо йому ще треба замінити тимчасовий пароль.

    Потрібна лише кільком ендпоінтам (/auth/me, /auth/change-password), щоб працівник із тимчасовим
    паролем міг його замінити. Для решти використовується `get_current_user` нижче.

    Токен дійсний, якщо підпис і термін у порядку, користувач існує, не вимкнений і номер покоління
    токенів збігається (його збільшує зміна пароля). Дані користувача беремо з БД на кожному запиті.
    """
    if credentials is None:
        raise UnauthorizedError(headers=_WWW_AUTHENTICATE)
    try:
        claims = decode_access_token(credentials.credentials, now)
    except TokenError as exc:
        if exc.reason == 'expired':
            # клієнту: токен оновлюється через /auth/refresh
            raise UnauthorizedError('Термін дії токена минув', code='token_expired', headers=_WWW_AUTHENTICATE)
        raise UnauthorizedError('Недійсний токен', code='invalid_token', headers=_WWW_AUTHENTICATE)

    user = await session.get(User, claims.user_id)
    if user is None or user.token_version != claims.token_version:
        raise UnauthorizedError('Недійсний токен', code='invalid_token', headers=_WWW_AUTHENTICATE)
    if not user.is_active:
        raise ForbiddenError('Обліковий запис вимкнено, зверніться до адміністратора', code='account_disabled')
    return user


async def get_current_user(user: User = Depends(get_current_user_any)) -> User:
    """Поточний користувач для всіх захищених ендпоінтів.

    Якщо пароль тимчасовий (його задав адміністратор), доступу немає, доки працівник не змінить його:
    403 `password_change_required`. У тестах цю залежність підміняють через `app.dependency_overrides`.
    """
    if user.must_change_password:
        raise ForbiddenError('Спершу змініть тимчасовий пароль', code='password_change_required')
    return user


def require_roles(*roles: UserRole):
    """Дозволяє доступ вказаним ролям. Адмін має доступ до всього."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role is not UserRole.admin and user.role not in roles:
            raise ForbiddenError()
        return user

    return checker
