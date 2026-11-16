import asyncio

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db

router = APIRouter(tags=['Health'])
log = structlog.get_logger('app.health')

DB_CHECK_TIMEOUT_SECONDS = 3


@router.get('/health')
async def health_check(db: AsyncSession = Depends(get_db)):
    """Для Docker/nginx healthcheck. 200: БД відповідає, 503: ні.

    Причину збою пишемо лише в лог: текст винятку може містити адресу й імʼя БД,
    назовні його віддавати не можна.
    """
    try:
        await asyncio.wait_for(db.execute(text('SELECT 1')), timeout=DB_CHECK_TIMEOUT_SECONDS)
    except Exception:
        log.error('health_db_unavailable', exc_info=True)
        return JSONResponse(status_code=503, content={'status': 'error', 'database': 'unavailable'})
    return {'status': 'ok', 'database': 'connected'}
