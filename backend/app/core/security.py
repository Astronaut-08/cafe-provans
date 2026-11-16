"""Хешування паролів персоналу.

scrypt зі стандартної бібліотеки: без додаткових залежностей, параметри з рекомендацій OWASP
(N=2^16, r=8, p=2, близько 64 MiB пам'яті на одне хешування). Параметри записуються в сам хеш,
тому їх можна підвищити пізніше: старі хеші продовжать працювати, а `needs_rehash`
підкаже, що пароль варто перехешувати при наступному вдалому вході.

Формат: scrypt$N$r$p$<сіль base64>$<хеш base64>

Хешування навмисно повільне й блокує потік: в async-коді викликати через
`await asyncio.to_thread(hash_password, ...)`.
"""
import base64
import hashlib
import hmac
import secrets

_ALGORITHM = 'scrypt'
_N = 2 ** 16
_R = 8
_P = 2
_SALT_BYTES = 16
_KEY_BYTES = 32


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # maxmem із запасом: ліміт за замовчуванням (32 MiB) менший за потрібне при N=2^16
    return hashlib.scrypt(
        password.encode('utf-8'), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=256 * n * r,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P)
    return f'{_ALGORITHM}${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}'


def _parse(stored_hash: str) -> tuple[int, int, int, bytes, bytes]:
    algorithm, n, r, p, salt, digest = stored_hash.split('$')
    if algorithm != _ALGORITHM:
        raise ValueError('unsupported algorithm')
    return int(n), int(r), int(p), base64.b64decode(salt, validate=True), base64.b64decode(digest, validate=True)


def verify_password(password: str, stored_hash: str) -> bool:
    """True, якщо пароль збігається. Пошкоджений або чужий хеш дає False, а не виняток."""
    try:
        n, r, p, salt, expected = _parse(stored_hash)
        actual = _derive(password, salt, n, r, p)
    except (ValueError, TypeError, OverflowError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored_hash: str) -> bool:
    """True, якщо хеш створений із застарілими параметрами (або не розпізнається)."""
    try:
        n, r, p, _, _ = _parse(stored_hash)
    except (ValueError, TypeError):
        return True
    return (n, r, p) != (_N, _R, _P)
