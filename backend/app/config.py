from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Налаштування застосунку з змінних оточення (або з файлу .env).

    Порядок пошуку .env: backend/.env, потім .env у корені репозиторію.
    У Docker змінні приходять із compose (env_file + environment), файл не потрібен.
    """
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / '.env', BACKEND_DIR.parent / '.env'),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    environment: Literal['development', 'test', 'production'] = 'development'
    # обов'язкова: без неї застосунок не стартує, а не працює з порожнім рядком
    database_url: str
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'
    # Через кому: CORS_ORIGINS=http://localhost:3000,http://localhost:5173
    # Порожньо = CORS вимкнений (сайт і API на одному домені через nginx).
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator('database_url')
    @classmethod
    def database_url_must_be_asyncpg(cls, v: str) -> str:
        if not v.startswith('postgresql+asyncpg://'):
            raise ValueError(
                'DATABASE_URL має починатися з postgresql+asyncpg:// '
                '(двигун асинхронний, «postgresql://» не підійде)'
            )
        return v

    @field_validator('cors_origins', mode='before')
    @classmethod
    def split_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip().rstrip('/') for origin in v.split(',') if origin.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == 'production'


settings = Settings()
