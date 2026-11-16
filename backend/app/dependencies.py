from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
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


async def get_current_user() -> User:
    """Поточний користувач із токена.

    ЗАГЛУШКА, закрита за замовчуванням: поки вхід не реалізований (Фаза 4), усі захищені
    ендпоінти відповідають 401. У Фазі 4 змінюється лише тіло цієї функції: розбір токена,
    пошук користувача, перевірка `is_active`. Усе, що на неї спирається, залишається як є.
    У тестах її підміняють через `app.dependency_overrides`.
    """
    raise UnauthorizedError()


def require_roles(*roles: UserRole):
    """Дозволяє доступ вказаним ролям. Адмін має доступ до всього."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role is not UserRole.admin and user.role not in roles:
            raise ForbiddenError()
        return user

    return checker
