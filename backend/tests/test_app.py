"""Наскрізні властивості застосунку: request id, єдиний формат помилок, health, CORS."""
import re

from fastapi import FastAPI

from app.config import settings
from app.dependencies import get_db
from app.main import create_app


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()['error']
    assert error['code'] == code
    assert set(error) == {'code', 'message', 'details', 'request_id'}
    return error


# ---------- request id ----------

async def test_request_id_is_generated(client):
    r = await client.get('/health')
    assert re.fullmatch(r'[0-9a-f]{32}', r.headers['X-Request-ID'])


async def test_valid_incoming_request_id_is_kept(client):
    r = await client.get('/health', headers={'X-Request-ID': 'nginx-abc-12345'})
    assert r.headers['X-Request-ID'] == 'nginx-abc-12345'


async def test_unsafe_incoming_request_id_is_replaced(client):
    for bad in ('short', 'has space in it!', 'x' * 200):
        r = await client.get('/health', headers={'X-Request-ID': bad})
        assert r.headers['X-Request-ID'] != bad
        assert re.fullmatch(r'[0-9a-f]{32}', r.headers['X-Request-ID'])


# ---------- єдиний формат помилок ----------

async def test_unknown_route_uses_error_envelope_with_matching_request_id(client):
    r = await client.get('/api/v1/nope')
    error = assert_error(r, 404, 'not_found')
    assert error['request_id'] == r.headers['X-Request-ID']


async def test_wrong_method_uses_error_envelope(client):
    assert_error(await client.put('/api/v1/categories'), 405, 'method_not_allowed')


async def test_validation_error_lists_fields_and_never_echoes_input(client, login_as):
    from app.db.enums import UserRole
    login_as(UserRole.admin)
    r = await client.post('/api/v1/categories', json={'name': '', 'password': 'topsecret-value'})
    error = assert_error(r, 422, 'validation_error')
    assert {d['field'] for d in error['details']} == {'name', 'password'}
    assert 'topsecret-value' not in r.text  # введене значення в відповідь не потрапляє


async def test_unhandled_exception_returns_generic_500_without_internals(application, client):
    @application.get('/_boom')
    async def boom():
        raise RuntimeError('db password is hunter2')

    r = await client.get('/_boom')
    error = assert_error(r, 500, 'internal_error')
    assert 'hunter2' not in r.text
    assert error['request_id']  # за ним у логах знаходимо причину


# ---------- health ----------

async def test_health_ok(client):
    r = await client.get('/health')
    assert r.status_code == 200
    assert r.json() == {'status': 'ok', 'database': 'connected'}


async def test_health_returns_503_when_db_is_down_and_hides_details(application, client):
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise ConnectionError('connection to server at "secret-host" failed')

    async def broken_db():
        yield BrokenSession()

    application.dependency_overrides[get_db] = broken_db
    r = await client.get('/health')
    assert r.status_code == 503  # раніше тут було 200 із тілом [503, {...}]
    assert r.json() == {'status': 'error', 'database': 'unavailable'}
    assert 'secret-host' not in r.text


# ---------- CORS ----------

def _preflight(app: FastAPI, origin: str):
    import httpx
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url='http://test')
    return client, client.options(
        '/api/v1/categories',
        headers={'Origin': origin, 'Access-Control-Request-Method': 'GET'},
    )


async def test_cors_allows_only_configured_origins(monkeypatch):
    monkeypatch.setattr(settings, 'cors_origins', ['http://localhost:3000'])
    client, request = _preflight(create_app(), 'http://localhost:3000')
    async with client:
        allowed = await request
    assert allowed.headers['access-control-allow-origin'] == 'http://localhost:3000'

    client, request = _preflight(create_app(), 'http://evil.example')
    async with client:
        denied = await request
    assert 'access-control-allow-origin' not in denied.headers


async def test_cors_is_off_when_not_configured():
    client, request = _preflight(create_app(), 'http://localhost:3000')
    async with client:
        r = await request
    assert 'access-control-allow-origin' not in r.headers
