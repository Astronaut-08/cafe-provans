import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = 'X-Request-ID'
# приймаємо id від клієнта/nginx лише якщо він безпечний для логів і заголовків
_VALID_REQUEST_ID = re.compile(r'^[A-Za-z0-9._-]{8,64}$')

log = structlog.get_logger('app.access')


class RequestContextMiddleware:
    """Request id + access-лог.

    - бере X-Request-ID із запиту (якщо валідний) або генерує новий;
    - додає його в кожен запис логу та у відповідь;
    - пише один рядок на запит: метод, шлях, статус, тривалість.
    Pure ASGI, а не BaseHTTPMiddleware: той ламає contextvars і фонові задачі.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        incoming = _request_id_from_headers(scope)
        request_id = incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        # request.state.request_id доступний обробникам помилок
        scope.setdefault('state', {})['request_id'] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500  # якщо виняток вилетить до відповіді, це й побачить лог
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            log.info(
                'request',
                method=scope['method'],
                path=scope['path'],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.clear_contextvars()


def _request_id_from_headers(scope: Scope) -> str | None:
    for key, value in scope['headers']:
        if key == b'x-request-id':
            return value.decode('latin-1')
    return None
