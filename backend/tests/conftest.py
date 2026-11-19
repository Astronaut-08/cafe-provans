"""Фікстури pytest.

Тести працюють з РЕАЛЬНИМ Postgres (потрібні pgvector і enum-типи, SQLite не підходить)
і завжди з окремою базою `<імʼя>_test`, а не з робочою. Адресу беремо з TEST_DATABASE_URL, а якщо
її немає, то з DATABASE_URL, додавши `_test` до імені БД. На початку кожного запуску базу
створюємо з нуля через `alembic upgrade head`, тож міграції теж перевіряються.
Між тестами дані відкочуються: кожен тест іде у зовнішній транзакції, а `commit()` сервісів
перетворюється на savepoint.

Запуск (з папки backend, БД має бути піднята):
    docker compose exec backend pip install -r requirements-dev.txt
    docker compose exec backend pytest
"""
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _resolve_test_url() -> str:
    explicit = os.environ.get('TEST_DATABASE_URL')
    if explicit:
        url = make_url(explicit)
    else:
        base = os.environ.get('DATABASE_URL')
        if not base:
            pytest.exit('Задайте TEST_DATABASE_URL або DATABASE_URL (тестова БД: <імʼя>_test).', returncode=2)
        url = make_url(base)
        url = url.set(database=f'{url.database}_test')
    # Страховка: нижче ми видаляємо й створюємо цю БД, робочу чіпати не можна
    if not (url.database or '').endswith('_test'):
        pytest.exit(f'Імʼя тестової БД має закінчуватися на _test, а не «{url.database}».', returncode=2)
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_url()

# ВАЖЛИВО: підміняємо ДО першого імпорту app, бо settings читається при імпорті.
# Відтепер увесь процес тестів бачить лише тестову БД.
os.environ['DATABASE_URL'] = TEST_DATABASE_URL
os.environ['ENVIRONMENT'] = 'test'
os.environ.setdefault('LOG_LEVEL', 'WARNING')
# Ключ підпису токенів лише для тестів. Задаємо жорстко (не setdefault): тест не має залежати від справжнього .env
os.environ['JWT_SECRET'] = 'test-only-jwt-secret-not-for-production-0123456789'
os.environ['OTP_SENDER'] = 'log'
os.environ.pop('CORS_ORIGINS', None)


async def _recreate_database(url_str: str) -> None:
    url = make_url(url_str)
    admin = create_async_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT', poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope='session', autouse=True)
def _database() -> None:
    asyncio.run(_recreate_database(TEST_DATABASE_URL))
    cfg = Config(str(BACKEND_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BACKEND_DIR / 'alembic'))
    command.upgrade(cfg, 'head')


def _new_session(connection) -> AsyncSession:
    # create_savepoint: commit() сесії лише «відпускає» savepoint (дані лишаються в зовнішній
    # транзакції), а close() без commit() відкочує його, як у справжньому застосунку
    return AsyncSession(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False)


@pytest.fixture(autouse=True)
def _cheap_password_hashing(request, monkeypatch):
    """scrypt із бойовими параметрами хешує ~0,2 с, а тести входу роблять це сотні разів. У тестах ставимо
    мінімальну вартість (N=2^10); логіка та сама. Справжні параметри перевіряє лише test_security."""
    if request.module.__name__.endswith('test_security'):
        return
    from app.core import security

    monkeypatch.setattr(security, '_N', 2 ** 10)


@pytest_asyncio.fixture
async def db_connection():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        try:
            yield conn
        finally:
            await outer.rollback()  # усе, що зробив тест, зникає
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_connection):
    """Сесія для підготовки даних і перевірок прямо в БД. Щоб запити API бачили її дані,
    потрібен `await db_session.commit()`."""
    async with _new_session(db_connection) as session:
        yield session


@pytest.fixture
def application(db_connection):
    from app.dependencies import get_db
    from app.main import create_app

    app = create_app()

    async def override_get_db():
        # НОВА сесія на кожен запит, як у проді. Одна спільна сесія приховувала б помилку
        # «сервіс забув commit()»: незакомічені дані були б видні наступному запиту.
        async with _new_session(db_connection) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest_asyncio.fixture
async def client(application):
    # raise_app_exceptions=False: необроблений виняток дає відповідь 500, як у справжнього сервера,
    # а не падає прямо в тесті
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url='http://test') as c:
        yield c


@pytest.fixture
def set_now(application):
    """set_now(datetime): «поточний момент» для маршрутів, що залежать від часу (години роботи, акції).
    Без виклику береться справжній час. Момент має бути aware (з поясом), найпростіше в UTC."""
    from app.dependencies import get_now

    def _set(moment) -> None:
        application.dependency_overrides[get_now] = lambda: moment

    return _set


@pytest.fixture
def login_as(application):
    """login_as(UserRole.waiter): підставляє поточного користувача з цією роллю.
    Без виклику користувач неавторизований (так само, як зараз у справжньому застосунку)."""
    from app.db.enums import UserRole
    from app.db.models.user import User
    from app.dependencies import get_current_user

    def _login(role: UserRole) -> None:
        user = User(id=1, login='tester', password_hash='x', full_name='Tester', role=role, is_active=True)
        application.dependency_overrides[get_current_user] = lambda: user

    return _login
