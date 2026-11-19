"""Єдиний формат помилок API.

Кожна помилка, незалежно від джерела, виглядає так:

    {"error": {"code": "not_found", "message": "Категорію не знайдено",
               "details": null, "request_id": "..."}}

`code` призначений для фронтенду (стабільний, англійською), `message` для людини
(українською), `details` потрібні лише валідації. Сервіси кидають підкласи AppError,
про HTTP вони нічого не знають: статус визначає сам клас помилки.
"""
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger('app.errors')


class AppError(Exception):
    status_code: int = 500
    code: str = 'internal_error'
    message: str = 'Внутрішня помилка сервера'

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers  # додаткові заголовки відповіді (WWW-Authenticate, Retry-After)
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = 401
    code = 'not_authenticated'
    message = 'Потрібна автентифікація'


class ForbiddenError(AppError):
    status_code = 403
    code = 'forbidden'
    message = 'Недостатньо прав для цієї дії'


class NotFoundError(AppError):
    status_code = 404
    code = 'not_found'
    message = 'Не знайдено'


class ConflictError(AppError):
    status_code = 409
    code = 'conflict'
    message = 'Конфлікт з поточним станом даних'


class TooManyRequestsError(AppError):
    """Забагато спроб (наприклад, акаунт тимчасово заблоковано після невдалих входів).
    Скільки чекати, клієнт бачить у `details.retry_after_seconds` і в заголовку Retry-After."""
    status_code = 429
    code = 'too_many_requests'
    message = 'Забагато спроб, спробуйте пізніше'


class UnprocessableError(AppError):
    """Запит синтаксично коректний, але порушує бізнес-правило
    (наприклад, сума замовлення менша за мінімум зони доставки)."""
    status_code = 422
    code = 'unprocessable'
    message = 'Запит не можна виконати'


def _request_id(request: Request) -> str | None:
    return request.scope.get('state', {}).get('request_id')


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {'error': {'code': code, 'message': message, 'details': details, 'request_id': _request_id(request)}}
    return JSONResponse(body, status_code=status_code, headers=headers)


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        log.error('app_error', code=exc.code, message=exc.message, exc_info=exc)
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details, headers=exc.headers)


_DEFAULT_MESSAGES = {
    400: 'Некоректний запит',
    404: 'Ресурс не знайдено',
    405: 'Цей метод не підтримується для цього адреса',
    413: 'Запит завеликий',
    415: 'Непідтримуваний тип даних',
}


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Помилки самого фреймворку: неіснуючий маршрут (404), не той метод (405) тощо.
    try:
        phrase = HTTPStatus(exc.status_code).phrase
        code = HTTPStatus(exc.status_code).name.lower()
    except ValueError:
        phrase, code = 'Помилка', 'http_error'
    # Стандартний англійський текст («Not Found») замінюємо на український; власний detail лишаємо
    if isinstance(exc.detail, str) and exc.detail != phrase:
        message = exc.detail
    else:
        message = _DEFAULT_MESSAGES.get(exc.status_code, phrase)
    return error_response(request, exc.status_code, code, message, headers=getattr(exc, 'headers', None))


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Навмисно без `input` із помилки pydantic: у запиті може бути пароль.
    details = [
        {
            'field': '.'.join(str(part) for part in err['loc'][1:]) or str(err['loc'][0]),
            'message': err['msg'],
            'type': err['type'],
        }
        for err in exc.errors()
    ]
    return error_response(request, 422, 'validation_error', 'Некоректні дані запиту', details)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Деталі лише в лог (разом із request_id), клієнту: загальне повідомлення.
    log.error('unhandled_exception', path=request.url.path, exc_info=exc)
    return error_response(request, 500, 'internal_error', 'Внутрішня помилка сервера')


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
