from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.dependencies import get_db 

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        # Виконуємо мінімальний запит до бази даних для перевірки зв'язку
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        # Якщо бази немає або вона не відповідає — повертаємо помилку 503
        return status.HTTP_503_SERVICE_UNAVAILABLE, {"status": "error", "database": str(e)}