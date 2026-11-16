from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import health
from app.api.router import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.db.session import engine

log = structlog.get_logger('app')


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info('startup', environment=settings.environment)
    yield
    await engine.dispose()  # коректно закриваємо пул з'єднань
    log.info('shutdown')


def create_app() -> FastAPI:
    configure_logging(settings.log_level, json_logs=settings.is_production)

    app = FastAPI(
        title='Cafe Provans API',
        version='0.1.0',
        lifespan=lifespan,
        # у продакшні документацію API не публікуємо
        docs_url=None if settings.is_production else '/docs',
        redoc_url=None,
        openapi_url=None if settings.is_production else '/openapi.json',
    )

    # Порядок важливий: middleware, додане пізніше, обгортає раніше додане.
    # RequestContext додається останнім, тож він зовнішній: request_id та лог є в усіх відповідях.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'],
            allow_headers=['Authorization', 'Content-Type', REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
            allow_credentials=False,  # вхід за Bearer-токеном, а не за cookie
        )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)

    @app.get('/', include_in_schema=False)
    async def root():
        return {'message': 'ok'}

    return app


app = create_app()
