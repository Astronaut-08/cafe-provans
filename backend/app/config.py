from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # --- вхід персоналу (JWT) ---
    # Обов'язковий і без значення за замовчуванням: «тимчасовий» ключ у коді рано чи пізно
    # потрапляє в продакшн. Згенерувати: python -c "import secrets; print(secrets.token_urlsafe(48))"
    # Змінити ключ = розлогінити всіх (старі токени перестають підходити).
    jwt_secret: SecretStr
    # Access-токен короткий (його не можна відкликати до завершення терміну), refresh довгий,
    # але зберігається в БД і відкликається (вихід, зміна пароля, вимкнення працівника).
    access_token_ttl_minutes: int = Field(default=30, ge=1)
    refresh_token_ttl_days: int = Field(default=14, ge=1)

    # --- відновлення пароля адміна: куди надсилати одноразовий код ---
    # log: код лише пишеться в лог (для розробки). smtp: лист на email адміна.
    # SMS додається окремим «відправником» у modules/auth/otp_sender.py, решта коду не міняється.
    otp_sender: Literal['log', 'smtp'] = 'log'
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None          # адреса відправника: Provans <no-reply@provans.example>
    smtp_security: Literal['starttls', 'ssl', 'none'] = 'starttls'  # starttls: порт 587, ssl: порт 465

    @field_validator('database_url')
    @classmethod
    def database_url_must_be_asyncpg(cls, v: str) -> str:
        if not v.startswith('postgresql+asyncpg://'):
            raise ValueError(
                'DATABASE_URL має починатися з postgresql+asyncpg:// '
                '(двигун асинхронний, «postgresql://» не підійде)'
            )
        return v

    @field_validator('jwt_secret')
    @classmethod
    def jwt_secret_must_be_long(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError('JWT_SECRET має містити щонайменше 32 символи')
        return v

    @field_validator('smtp_host', 'smtp_user', 'smtp_password', 'smtp_from', mode='before')
    @classmethod
    def empty_smtp_value_is_none(cls, v):
        # у .env рядок «SMTP_HOST=» дає порожній рядок: це те саме, що «не задано»
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode='after')
    def check_otp_sender(self) -> 'Settings':
        if self.otp_sender == 'smtp' and not (self.smtp_host and self.smtp_from):
            raise ValueError('OTP_SENDER=smtp потребує SMTP_HOST і SMTP_FROM')
        if self.is_production and self.otp_sender == 'log':
            # одноразові коди в логах бачить будь-хто з доступом до логів
            raise ValueError('У продакшні OTP_SENDER має бути smtp: код відновлення не можна писати в лог')
        return self

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
