import pytest
from pydantic import ValidationError

from app.config import Settings

URL = 'postgresql+asyncpg://u:p@db:5432/app'


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)  # _env_file=None: не підтягувати справжній .env


def test_asyncpg_url_is_accepted():
    assert make(database_url=URL).database_url == URL


@pytest.mark.parametrize('url', ['postgresql://u:p@db/app', 'postgres://u:p@db/app', 'sqlite:///x.db', ''])
def test_non_asyncpg_url_is_rejected_with_clear_message(url):
    with pytest.raises(ValidationError, match='postgresql\\+asyncpg'):
        make(database_url=url)


def test_cors_origins_from_comma_separated_string():
    s = make(database_url=URL, cors_origins='http://localhost:3000/, http://localhost:5173 ,')
    assert s.cors_origins == ['http://localhost:3000', 'http://localhost:5173']


def test_cors_is_off_by_default():
    assert make(database_url=URL).cors_origins == []


def test_environment_and_log_level_are_validated():
    with pytest.raises(ValidationError):
        make(database_url=URL, environment='staging')
    with pytest.raises(ValidationError):
        make(database_url=URL, log_level='LOUD')


SMTP = dict(otp_sender='smtp', smtp_host='mail.example.com', smtp_from='Provans <no-reply@example.com>')


def test_is_production_flag():
    assert make(database_url=URL, environment='production', **SMTP).is_production is True
    assert make(database_url=URL).is_production is False


# ---------- вхід персоналу ----------

def test_jwt_secret_is_required(monkeypatch):
    # без ключа застосунок не стартує, а не працює з «тимчасовим» значенням із коду
    monkeypatch.delenv('JWT_SECRET')
    with pytest.raises(ValidationError, match='jwt_secret'):
        make(database_url=URL)


@pytest.mark.parametrize('secret', ['', 'short', 'x' * 31])
def test_short_jwt_secret_is_rejected(secret):
    with pytest.raises(ValidationError, match='JWT_SECRET'):
        make(database_url=URL, jwt_secret=secret)


def test_jwt_secret_is_not_printed():
    settings = make(database_url=URL, jwt_secret='s' * 40, smtp_password='hunter2-hunter2')
    assert 's' * 40 not in repr(settings) and 'hunter2' not in repr(settings)
    assert settings.jwt_secret.get_secret_value() == 's' * 40


def test_token_lifetimes_have_sane_defaults_and_bounds():
    s = make(database_url=URL)
    assert (s.access_token_ttl_minutes, s.refresh_token_ttl_days) == (30, 14)
    with pytest.raises(ValidationError):
        make(database_url=URL, access_token_ttl_minutes=0)
    with pytest.raises(ValidationError):
        make(database_url=URL, refresh_token_ttl_days=0)


def test_smtp_sender_needs_host_and_from():
    with pytest.raises(ValidationError, match='SMTP_HOST'):
        make(database_url=URL, otp_sender='smtp')
    with pytest.raises(ValidationError, match='SMTP_HOST'):
        make(database_url=URL, otp_sender='smtp', smtp_host='mail.example.com')
    assert make(database_url=URL, **SMTP).otp_sender == 'smtp'


def test_empty_smtp_values_from_env_file_mean_not_set():
    # у .env рядок «SMTP_HOST=» читається як порожній рядок
    s = make(database_url=URL, smtp_host='', smtp_user=' ', smtp_password='', smtp_from='')
    assert (s.smtp_host, s.smtp_user, s.smtp_password, s.smtp_from) == (None, None, None, None)


def test_production_refuses_to_log_otp_codes():
    with pytest.raises(ValidationError, match='OTP_SENDER'):
        make(database_url=URL, environment='production', otp_sender='log')
    # у розробці лог дозволений
    assert make(database_url=URL, environment='development', otp_sender='log').otp_sender == 'log'
