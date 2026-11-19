"""Токени входу: access (JWT), refresh (випадковий рядок) і одноразові коди (OTP).

Усі функції чисті: час приходить параметром `now` (його дає залежність `get_now`), тому поведінку
«токен прострочився» легко перевірити в тесті без очікування.

Access-токен: короткий JWT (HS256). У ньому лише id користувача (`sub`) і номер покоління токенів (`tv`).
Роль у токен НЕ кладемо: її читаємо з БД на кожному запиті, тож зміна ролі чи вимкнення працівника
діють одразу, а не коли закінчиться токен.

Refresh-токен: випадковий рядок, а не JWT. У БД лежить лише його SHA-256 (див. models/refresh_token.py).
Перебрати такий токен неможливо (384 біти випадковості), тому повільний хеш типу scrypt тут не потрібен.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import jwt

from app.config import settings

_ALGORITHM = 'HS256'
_ACCESS_TYPE = 'access'


class TokenError(Exception):
    """Access-токен не підходить. `reason`: 'expired' (термін минув, клієнту варто оновити токен)
    або 'invalid' (підробка, сміття, чужий ключ: оновлювати марно)."""

    def __init__(self, reason: Literal['expired', 'invalid']) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    token_version: int


def _secret() -> str:
    return settings.jwt_secret.get_secret_value()


def create_access_token(user_id: int, token_version: int, now: datetime) -> tuple[str, int]:
    """Повертає (токен, скільки секунд він діє)."""
    lifetime = timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        'typ': _ACCESS_TYPE,
        'sub': str(user_id),  # за стандартом sub це рядок
        'tv': token_version,
        'iat': int(now.timestamp()),
        'exp': int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM), int(lifetime.total_seconds())


def decode_access_token(token: str, now: datetime) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            _secret(),
            # лише наш алгоритм: так не пройде токен із alg=none чи іншим «своїм» алгоритмом
            algorithms=[_ALGORITHM],
            # Терміни перевіряємо самі за `now` (щоб час можна було підмінити в тесті), а не за годинником бібліотеки
            options={'require': ['exp', 'iat', 'sub'], 'verify_exp': False, 'verify_iat': False, 'verify_nbf': False},
        )
    except jwt.PyJWTError:
        raise TokenError('invalid') from None

    exp, tv = payload.get('exp'), payload.get('tv')
    # bool це підклас int, але True як «термін» чи «версія» тут сміття
    if payload.get('typ') != _ACCESS_TYPE or not _is_int(exp) or not _is_int(tv):
        raise TokenError('invalid')
    try:
        user_id = int(payload['sub'])
    except (TypeError, ValueError):
        raise TokenError('invalid') from None

    if now.timestamp() >= exp:
        raise TokenError('expired')
    return AccessClaims(user_id=user_id, token_version=tv)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------- refresh-токен ----------

def new_refresh_token() -> tuple[str, str]:
    """Повертає (токен для клієнта, його хеш для БД)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


# ---------- одноразовий код для відновлення пароля ----------

def new_otp_code() -> str:
    """Шість цифр, з ведучими нулями ('004217')."""
    return f'{secrets.randbelow(10 ** 6):06d}'


def hash_otp(user_id: int, code: str) -> str:
    """HMAC із ключем із налаштувань. Просте SHA-256 тут не годиться: кодів лише мільйон, і з витоку БД
    їх перебрали б за мить. З ключем, якого в БД немає, перебір без доступу до сервера неможливий.
    user_id входить у повідомлення, щоб однаковий код двох користувачів мав різні хеші."""
    message = f'otp:{user_id}:{code}'.encode('utf-8')
    return hmac.new(_secret().encode('utf-8'), message, hashlib.sha256).hexdigest()


def otp_matches(user_id: int, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(user_id, code), stored_hash)
