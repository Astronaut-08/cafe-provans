"""Керування персоналом (лише для адміністратора).

Правила:
- працівників не видаляють, а вимикають (`is_active=false`): на них посилаються замовлення та історія;
- адміністратор НІКОЛИ не бачить пароля працівника (у БД лише хеш). Якщо пароль забули, адміністратор
  скидає його: система генерує тимчасовий, показує один раз, а працівник мусить замінити його при першому вході;
- в системі завжди лишається хоча б один активний адмін.
"""
import asyncio
import secrets
from collections.abc import Sequence
from datetime import datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.security import hash_password
from app.db.enums import UserRole
from app.db.models.user import User
from app.dependencies import get_db
from app.modules.auth.service import revoke_all_tokens, set_password
from app.modules.users.schemas import UserCreate, UserUpdate

# Без символів, які плутають на слух і на око (0/O, 1/l/I): пароль диктують по телефону чи пишуть на папері
_TEMP_PASSWORD_ALPHABET = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
_TEMP_PASSWORD_LENGTH = 12


def generate_temporary_password() -> str:
    return ''.join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(_TEMP_PASSWORD_LENGTH))


def _admin_needs_email() -> UnprocessableError:
    return UnprocessableError(
        'Адміністратору потрібен email: на нього надходить код відновлення пароля', code='admin_email_required',
    )


def _translate_integrity_error(exc: IntegrityError) -> Exception:
    # Postgres пише назву обмеження в текст помилки: за нею й розрізняємо, що саме порушено
    text = str(exc.orig)
    if 'uq_users_login' in text:
        return ConflictError('Такий логін уже існує', code='login_taken')
    if 'uq_users_phone' in text:
        return ConflictError('Такий телефон уже використовується', code='phone_taken')
    if 'uq_users_email' in text:
        return ConflictError('Такий email уже використовується', code='email_taken')
    if 'fk_users_location_id_locations' in text:
        return UnprocessableError('Заклад не знайдено', code='location_not_found')
    return exc


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, *, role: UserRole | None = None, is_active: bool | None = None, location_id: int | None = None,
    ) -> Sequence[User]:
        query = select(User).order_by(User.full_name, User.id)
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if location_id is not None:
            query = query.where(User.location_id == location_id)
        return (await self.session.scalars(query)).all()

    async def get(self, user_id: int) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError('Працівника не знайдено')
        return user

    async def create(self, data: UserCreate) -> User:
        if data.role is UserRole.admin and not data.email:
            raise _admin_needs_email()
        user = User(
            login=data.login,
            password_hash=await asyncio.to_thread(hash_password, data.password),
            full_name=data.full_name,
            phone=data.phone,
            email=data.email,
            role=data.role,
            location_id=data.location_id,
            # пароль задав адміністратор, отже його знає не лише власник: хай працівник замінить його власним
            must_change_password=True,
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _translate_integrity_error(exc)
        return user

    async def update(self, user_id: int, data: UserUpdate, now: datetime) -> User:
        user = await self.get(user_id)
        changes = data.model_dump(exclude_unset=True)

        if user.role is UserRole.admin and user.is_active and ('role' in changes or 'is_active' in changes):
            # Адмін може перестати бути активним адміном. Тоді перевіряємо, що є ще хтось
            await self._lock_active_admins()
            await self.session.refresh(user)  # після очікування блокування дані могли змінитися
            still_active_admin = user.role is UserRole.admin and user.is_active
            stays_admin = changes.get('role', user.role) is UserRole.admin and changes.get('is_active', user.is_active)
            if still_active_admin and not stays_admin and not await self._has_other_active_admin(user.id):
                raise ConflictError(
                    'Не можна вимкнути або понизити останнього активного адміністратора', code='last_admin',
                )

        new_role = changes.get('role', user.role)
        new_email = changes.get('email', user.email)
        if new_role is UserRole.admin and not new_email:
            raise _admin_needs_email()

        deactivated = user.is_active and changes.get('is_active') is False
        for field, value in changes.items():
            setattr(user, field, value)
        if deactivated:
            # Вимкнений працівник втрачає доступ негайно: його access-токени (через token_version) і refresh-токени
            user.token_version += 1
            await revoke_all_tokens(self.session, user.id, now)

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _translate_integrity_error(exc)
        return user

    async def reset_password(self, user_id: int, actor: User, now: datetime) -> str:
        """Скидає пароль працівника і повертає ТИМЧАСОВИЙ пароль (його можна побачити лише тут і лише раз)."""
        if user_id == actor.id:
            raise ForbiddenError(
                'Свій пароль змінюйте через «Змінити пароль» або «Забув пароль»', code='cannot_reset_own_password',
            )
        user = await self.get(user_id)
        temporary = generate_temporary_password()
        await set_password(self.session, user, temporary, now, must_change=True)
        await self.session.commit()
        return temporary

    # ---------- останній адмін ----------

    async def _lock_active_admins(self) -> None:
        # Блокуємо рядки всіх активних адмінів у ПОРЯДКУ id. Двоє адмінів, що одночасно понижують один одного,
        # стають у чергу (а не пройдуть обидва й залишать систему без адміна). Однаковий порядок виключає взаємне блокування.
        await self.session.execute(
            select(User.id).where(User.role == UserRole.admin, User.is_active).order_by(User.id).with_for_update()
        )

    async def _has_other_active_admin(self, user_id: int) -> bool:
        other = await self.session.execute(
            select(User.id).where(User.role == UserRole.admin, User.is_active, User.id != user_id).limit(1)
        )
        return other.first() is not None


def get_user_service(session: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(session)
