from fastapi import APIRouter

from app.modules.categories.router import router as categories_router

# Усе бізнес-API живе під /api/v1. Новий модуль підключається одним рядком тут.
# (/health лежить поза версією: це перевірка інфраструктури, а не частина API.)
api_router = APIRouter(prefix='/api/v1')

api_router.include_router(categories_router)
