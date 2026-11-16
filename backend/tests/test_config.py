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


def test_is_production_flag():
    assert make(database_url=URL, environment='production').is_production is True
    assert make(database_url=URL).is_production is False
