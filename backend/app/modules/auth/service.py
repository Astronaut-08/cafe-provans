"""Вхід персоналу: пароль -> access + refresh токени, оновлення, вихід, зміна пароля, відновлення пароля адміна.

Правила модуля:
- час приходить параметром `now` (залежність get_now), тож його можна підміняти в тестах;
- все, що має ЗБЕРЕГТИСЯ перед відповідною помилкою (лічильник невдалих входів, відкликання токенів при
  підозрі на крадіжку), комітимо ДО `raise`: помилка відкочує незакомічене, і лічильник ніколи б не росла.
"""
import asyncio
import functools
import math
import secrets
import uuid
from datetime import datetime, timedelta

import structlog
from fastapi import Depends
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ForbiddenError, TooManyRequestsError, UnauthorizedError, UnprocessableError
from app.core.security import hash_password, needs_rehash, verify_password
from app.core.tokens import (
    create_access_token, hash_otp, hash_refresh_token, new_otp_code, new_refresh_token, otp_matches,
)
from app.db.enums import UserRole
from app.db.models.password_reset_otp import PasswordResetOtp
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User
from app.dependencies import get_db
from app.modules.auth.otp_sender import OtpMessage
from app.modules.auth.schemas import TokenResponse
from app.modules.users.schemas import UserRead

log = structlog.get_logger('app.auth')

# Захист від підбору пароля: після стількох невдалих входів поспіль вхід блокується на стільки часу.
MAX_FAILED_LOGINS = 5
LOCK_DURATION = timedelta(minutes=15)

# Відновлення пароля: код діє 10 хвилин, дає 5 спроб, а нових кодів можна просити не більше 3 на годину.
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_REQUESTS_PER_WINDOW = 3
OTP_REQUEST_WINDOW = timedelta(hours=1)


def _invalid_credentials() -> UnauthorizedError:
    # Однакове повідомлення для «немає такого логіна» і «пароль не той»: за відповіддю логіни не вгадати
    return UnauthorizedError('Невірний логін або пароль', code='invalid_credentials')


def _invalid_refresh_token() -> UnauthorizedError:
    return UnauthorizedError('Сесія недійсна, увійдіть знову', code='invalid_refresh_token')


def _invalid_otp() -> UnprocessableError:
    # Одне повідомлення на всі випадки: невірний код, прострочений, вичерпані спроби, немає такого акаунта
    return UnprocessableError('Невірний або прострочений код', code='invalid_otp')


def _locked_error(locked_until: datetime, now: datetime) -> TooManyRequestsError:
    seconds = max(1, math.ceil((locked_until - now).total_seconds()))
    minutes = math.ceil(seconds / 60)
    return TooManyRequestsError(
        f'Забагато невдалих спроб входу. Спробуйте за {minutes} хв',
        code='account_locked',
        details={'retry_after_seconds': seconds},
        headers={'Retry-After': str(seconds)},
    )


@functools.cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


async def set_password(session: AsyncSession, user: User, new_password: str, now: datetime, *, must_change: bool) -> None:
    """Єдине місце, де користувачеві міняється пароль (зміна, відновлення, скидання адміністратором).

    Крім хеша: збільшує `token_version` (усі видані access-токени одразу недійсні), відкликає всі refresh-токени
    (вихід з усіх пристроїв) і знімає блокування. Нічого не комітить: це робить викликач.
    """
    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    user.must_change_password = must_change
    user.token_version += 1
    user.failed_login_attempts = 0
    user.locked_until = None
    await revoke_all_tokens(session, user.id, now)


async def revoke_all_tokens(session: AsyncSession, user_id: int, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- допоміжне ----------

    async def _find_by_login(self, login: str) -> User | None:
        return (await self.session.execute(select(User).where(User.login == login))).scalar_one_or_none()

    @staticmethod
    def _ensure_not_locked(user: User, now: datetime) -> None:
        if user.locked_until is not None and user.locked_until > now:
            raise _locked_error(user.locked_until, now)

    async def _register_failed_attempt(self, user: User, now: datetime) -> datetime | None:
        """Рахує невдалу спробу. Повертає момент, до якого заблоковано, якщо ця спроба стала останньою
        допустимою. Лічильник збільшується в самій БД (`x = x + 1`), а не в Python: так паралельні запити
        не затирають один одного й не дають зловмисникові зайвих спроб."""
        attempts = (await self.session.execute(
            update(User).where(User.id == user.id)
            .values(failed_login_attempts=User.failed_login_attempts + 1)
            .returning(User.failed_login_attempts)
        )).scalar_one()
        locked_until = None
        if attempts >= MAX_FAILED_LOGINS:
            locked_until = now + LOCK_DURATION
            await self.session.execute(
                update(User).where(User.id == user.id).values(failed_login_attempts=0, locked_until=locked_until)
            )
            log.warning('account_locked', user_id=user.id, locked_until=locked_until.isoformat())
        await self.session.commit()  # ДО raise у викликача (див. docstring модуля)
        return locked_until

    async def _issue_tokens(self, user: User, now: datetime, family_id: uuid.UUID | None = None) -> TokenResponse:
        raw_refresh, refresh_hash = new_refresh_token()
        self.session.add(RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),  # новий вхід = нова «родина», оновлення лишає ту саму
            token_hash=refresh_hash,
            created_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        ))
        access, expires_in = create_access_token(user.id, user.token_version, now)
        return TokenResponse(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=expires_in,
            must_change_password=user.must_change_password,
            user=UserRead.model_validate(user),
        )

    async def _revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    # ---------- вхід ----------

    async def login(self, login: str, password: str, now: datetime) -> TokenResponse:
        user = await self._find_by_login(login)
        if user is None:
            # Хешуємо пароль у будь-якому разі: інакше «немає такого логіна» відповідає миттєво, а «є» через
            # 100+ мс, і за часом відповіді можна вгадати існуючі логіни.
            await asyncio.to_thread(verify_password, password, _dummy_hash())
            raise _invalid_credentials()

        # Заблокованому пароль навіть не перевіряємо: інакше підбір тривав би й під час блокування
        self._ensure_not_locked(user, now)

        if not await asyncio.to_thread(verify_password, password, user.password_hash):
            locked_until = await self._register_failed_attempt(user, now)
            if locked_until is not None:
                raise _locked_error(locked_until, now)
            raise _invalid_credentials()

        if not user.is_active:
            # пароль вірний, тож пояснити причину відмови безпечно
            raise ForbiddenError('Обліковий запис вимкнено, зверніться до адміністратора', code='account_disabled')

        if user.failed_login_attempts or user.locked_until is not None:
            await self.session.execute(
                update(User).where(User.id == user.id).values(failed_login_attempts=0, locked_until=None)
            )
            user.failed_login_attempts, user.locked_until = 0, None
        if needs_rehash(user.password_hash):
            # параметри хешування з часом посилюються: старий хеш оновлюємо, поки пароль у нас на руках
            user.password_hash = await asyncio.to_thread(hash_password, password)

        # Прибираємо прострочені refresh-токени цього користувача, щоб таблиця не росла вічно
        await self.session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.expires_at <= now)
        )
        response = await self._issue_tokens(user, now)
        await self.session.commit()
        return response

    # ---------- оновлення токена і вихід ----------

    async def refresh(self, raw_token: str, now: datetime) -> TokenResponse:
        """Міняє refresh-токен на нову пару токенів. Старий refresh відкликається (ротація).

        Якщо ВІДКЛИКАНИЙ токен приходить знову, то його або вкрали, або клієнт помилково використав двічі.
        Відрізнити не можна, тож відкликаємо весь ланцюжок: чесний користувач увійде знову, а злодій лишиться ні з чим.
        """
        # FOR UPDATE: два одночасні запити з одним токеном виконуються по черзі, і другий побачить його відкликаним
        token = (await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).with_for_update()
        )).scalar_one_or_none()
        if token is None:
            raise _invalid_refresh_token()

        if token.revoked_at is not None:
            await self._revoke_family(token.family_id, now)
            await self.session.commit()  # ДО raise
            log.warning('refresh_token_reuse_detected', user_id=token.user_id)
            raise _invalid_refresh_token()
        if token.expires_at <= now:
            raise _invalid_refresh_token()

        user = await self.session.get(User, token.user_id)
        if user is None:
            raise _invalid_refresh_token()
        if not user.is_active:
            raise ForbiddenError('Обліковий запис вимкнено, зверніться до адміністратора', code='account_disabled')

        token.revoked_at = now
        response = await self._issue_tokens(user, now, family_id=token.family_id)
        await self.session.commit()
        return response

    async def logout(self, raw_token: str, now: datetime) -> None:
        """Завершує цей вхід (увесь ланцюжок оновлень). Невідомий токен не помилка: вихід ідемпотентний.
        Уже виданий access-токен діє до кінця свого короткого терміну; повністю його не відкликати."""
        token = (await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )).scalar_one_or_none()
        if token is not None:
            await self._revoke_family(token.family_id, now)
            await self.session.commit()

    # ---------- зміна пароля ----------

    async def change_password(self, user: User, current_password: str, new_password: str, now: datetime) -> TokenResponse:
        """Свій пароль міняє будь-який працівник, зокрема той, кому адміністратор видав тимчасовий.
        Усі інші входи (інші пристрої) завершуються, а цьому клієнту одразу видаємо нову пару токенів."""
        self._ensure_not_locked(user, now)
        if not await asyncio.to_thread(verify_password, current_password, user.password_hash):
            # з викраденим токеном пароль підбирали б безкарно, тож рахуємо як звичайну невдалу спробу входу
            locked_until = await self._register_failed_attempt(user, now)
            if locked_until is not None:
                raise _locked_error(locked_until, now)
            raise UnprocessableError('Поточний пароль невірний', code='invalid_current_password')
        if new_password == current_password:
            raise UnprocessableError('Новий пароль має відрізнятися від поточного', code='same_password')

        await set_password(self.session, user, new_password, now, must_change=False)
        response = await self._issue_tokens(user, now)
        await self.session.commit()
        return response

    # ---------- відновлення пароля адміна ----------

    async def forgot_password(self, login: str, now: datetime) -> OtpMessage | None:
        """Створює одноразовий код і повертає те, що треба надіслати (саму відправку робить роутер у фоні).

        Повертає None (і нічого не створює), якщо відновлення недоступне: немає такого логіна, це не адмін
        (решті персоналу пароль скидає адміністратор), акаунт вимкнено, немає email або вичерпано ліміт запитів.
        Клієнт про причину не дізнається: відповідь завжди однакова.
        """
        user = await self._find_by_login(login)
        if user is None or user.role is not UserRole.admin or not user.is_active or not user.email:
            log.info('password_reset_skipped', reason='not_eligible')
            return None

        window_start = now - OTP_REQUEST_WINDOW
        recent = (await self.session.execute(
            select(func.count()).select_from(PasswordResetOtp)
            .where(PasswordResetOtp.user_id == user.id, PasswordResetOtp.created_at > window_start)
        )).scalar_one()
        if recent >= OTP_REQUESTS_PER_WINDOW:
            log.warning('password_reset_rate_limited', user_id=user.id)
            return None

        # старіші за вікно коди вже ні для чого не потрібні (код живе 10 хв, вікно 1 год)
        await self.session.execute(
            delete(PasswordResetOtp).where(PasswordResetOtp.user_id == user.id, PasswordResetOtp.created_at <= window_start)
        )
        code = new_otp_code()
        self.session.add(PasswordResetOtp(
            user_id=user.id, code_hash=hash_otp(user.id, code), created_at=now, expires_at=now + OTP_TTL,
        ))
        await self.session.commit()
        return OtpMessage(
            email=user.email, login=user.login, full_name=user.full_name, code=code,
            ttl_minutes=int(OTP_TTL.total_seconds() // 60),
        )

    async def reset_password(self, login: str, code: str, new_password: str, now: datetime) -> None:
        """Ставить новий пароль за кодом. Перевіряється лише НАЙНОВІШИЙ код користувача (новий запит скасовує
        попередні). Успішне відновлення знімає й блокування входу: так адмін, якому підбирали пароль, повертає доступ."""
        user = await self._find_by_login(login)
        otp = None
        if user is not None and user.role is UserRole.admin and user.is_active:
            otp = (await self.session.execute(
                select(PasswordResetOtp)
                .where(
                    PasswordResetOtp.user_id == user.id,
                    PasswordResetOtp.used_at.is_(None),
                    PasswordResetOtp.expires_at > now,
                    PasswordResetOtp.attempts < OTP_MAX_ATTEMPTS,
                )
                .order_by(PasswordResetOtp.created_at.desc(), PasswordResetOtp.id.desc())
                .limit(1)
                .with_for_update()
            )).scalar_one_or_none()
        if user is None or otp is None:
            raise _invalid_otp()

        if not otp_matches(user.id, code, otp.code_hash):
            await self.session.execute(
                update(PasswordResetOtp).where(PasswordResetOtp.id == otp.id)
                .values(attempts=PasswordResetOtp.attempts + 1)
            )
            await self.session.commit()  # ДО raise, інакше спроби не рахувалися б
            raise _invalid_otp()

        # код використано; решту незакритих кодів теж гасимо
        await self.session.execute(
            update(PasswordResetOtp)
            .where(PasswordResetOtp.user_id == user.id, PasswordResetOtp.used_at.is_(None))
            .values(used_at=now)
        )
        await set_password(self.session, user, new_password, now, must_change=False)
        await self.session.commit()
        log.info('password_reset_done', user_id=user.id)


def get_auth_service(session: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(session)
