"""Токени й одноразові коди: чисті функції, без БД."""
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from app.core import tokens
from app.core.tokens import (
    TokenError, create_access_token, decode_access_token, hash_otp, hash_refresh_token, new_otp_code,
    new_refresh_token, otp_matches,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
SECRET = settings.jwt_secret.get_secret_value()


def forge(payload: dict, key: str = SECRET, algorithm: str = 'HS256') -> str:
    base = {'typ': 'access', 'sub': '7', 'tv': 0, 'iat': int(NOW.timestamp()), 'exp': int((NOW + timedelta(minutes=5)).timestamp())}
    return jwt.encode({**base, **payload}, key, algorithm=algorithm)


def reason(token: str, now: datetime = NOW) -> str:
    with pytest.raises(TokenError) as exc:
        decode_access_token(token, now)
    return exc.value.reason


# ---------- access-токен ----------

def test_roundtrip_returns_user_and_token_version():
    token, expires_in = create_access_token(7, 3, NOW)
    claims = decode_access_token(token, NOW)
    assert (claims.user_id, claims.token_version) == (7, 3)
    assert expires_in == settings.access_token_ttl_minutes * 60


def test_token_does_not_carry_role_or_password_data():
    token, _ = create_access_token(7, 0, NOW)
    payload = jwt.decode(token, options={'verify_signature': False})
    assert set(payload) == {'typ', 'sub', 'tv', 'iat', 'exp'}


def test_issued_at_and_expiry_are_computed_from_the_given_now():
    token, expires_in = create_access_token(7, 0, NOW)
    payload = jwt.decode(token, options={'verify_signature': False})
    assert payload['iat'] == int(NOW.timestamp())
    assert payload['exp'] == int(NOW.timestamp()) + expires_in


def test_expiry_boundary_uses_the_given_now_not_the_real_clock():
    token, expires_in = create_access_token(7, 0, NOW)
    last_good = NOW + timedelta(seconds=expires_in - 1)
    assert decode_access_token(token, last_good).user_id == 7
    assert reason(token, NOW + timedelta(seconds=expires_in)) == 'expired'
    assert reason(token, NOW + timedelta(days=1)) == 'expired'


def test_token_issued_in_the_future_relative_to_real_clock_still_decodes():
    # час у тестах і в логіці береться з параметра, а не з годинника бібліотеки
    far_future = datetime(2040, 1, 1, tzinfo=UTC)
    token, _ = create_access_token(7, 0, far_future)
    assert decode_access_token(token, far_future).user_id == 7


@pytest.mark.parametrize('token', ['', 'abc', 'a.b.c', 'Bearer x', 'x' * 500])
def test_garbage_is_invalid(token):
    assert reason(token) == 'invalid'


def test_wrong_secret_is_invalid():
    assert reason(forge({}, key='another-secret-another-secret-another-secret')) == 'invalid'


def test_tampered_payload_is_invalid():
    head, _, sig = forge({}).split('.')
    other = forge({'sub': '1'}).split('.')[1]
    assert reason(f'{head}.{other}.{sig}') == 'invalid'


def test_alg_none_is_rejected():
    unsigned = jwt.encode({'typ': 'access', 'sub': '7', 'tv': 0, 'iat': 1, 'exp': 4_000_000_000}, None, algorithm='none')
    assert reason(unsigned) == 'invalid'


@pytest.mark.filterwarnings('ignore:The HMAC key')
def test_other_hmac_algorithm_is_rejected():
    # HS512 з правильним ключем: приймається лише той алгоритм, яким підписуємо ми
    assert reason(forge({}, algorithm='HS512')) == 'invalid'


@pytest.mark.parametrize('claims', [
    {'typ': 'refresh'}, {'typ': None}, {'sub': 'abc'}, {'sub': ''}, {'sub': None}, {'tv': 'x'}, {'tv': True},
    {'tv': 1.5}, {'exp': 'soon'}, {'exp': True}, {'exp': None},
])
def test_malformed_claims_are_invalid(claims):
    assert reason(forge(claims)) == 'invalid'


@pytest.mark.parametrize('missing', ['exp', 'iat', 'sub', 'tv', 'typ'])
def test_missing_claims_are_invalid(missing):
    payload = {'typ': 'access', 'sub': '7', 'tv': 0, 'iat': int(NOW.timestamp()), 'exp': int((NOW + timedelta(minutes=5)).timestamp())}
    del payload[missing]
    assert reason(jwt.encode(payload, SECRET, algorithm='HS256')) == 'invalid'


# ---------- refresh-токен ----------

def test_refresh_tokens_are_long_unique_and_hashed_consistently():
    raw1, hash1 = new_refresh_token()
    raw2, hash2 = new_refresh_token()
    assert raw1 != raw2 and hash1 != hash2
    assert len(raw1) >= 64
    assert hash1 == hash_refresh_token(raw1) and len(hash1) == 64
    assert raw1 not in hash1


# ---------- одноразові коди ----------

def test_otp_code_is_six_digits_with_leading_zeros(monkeypatch):
    monkeypatch.setattr(tokens.secrets, 'randbelow', lambda n: 42)
    assert new_otp_code() == '000042'
    assert all(len(new_otp_code()) == 6 and new_otp_code().isdigit() for _ in range(200))


def test_otp_uses_the_whole_range(monkeypatch):
    seen = []
    monkeypatch.setattr(tokens.secrets, 'randbelow', lambda n: seen.append(n) or 0)
    new_otp_code()
    assert seen == [1_000_000]


def test_otp_hash_depends_on_user_code_and_secret(monkeypatch):
    base = hash_otp(1, '123456')
    assert base == hash_otp(1, '123456')
    assert base != hash_otp(2, '123456')   # той самий код у двох користувачів дає різні хеші
    assert base != hash_otp(1, '123457')
    assert '123456' not in base
    monkeypatch.setattr(settings, 'jwt_secret', type(settings.jwt_secret)('another-secret-another-secret-another-secret'))
    assert hash_otp(1, '123456') != base   # без ключа з налаштувань код з витоку БД не перебрати


def test_otp_matches():
    stored = hash_otp(5, '000123')
    assert otp_matches(5, '000123', stored)
    assert not otp_matches(5, '000124', stored)
    assert not otp_matches(6, '000123', stored)
    assert not otp_matches(5, '000123', 'garbage')
