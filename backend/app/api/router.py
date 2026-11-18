from fastapi import APIRouter

from app.modules.allergens.router import router as allergens_router
from app.modules.categories.router import router as categories_router
from app.modules.delivery.router import router as delivery_router
from app.modules.locations.router import router as locations_router
from app.modules.menu.router import router as menu_router
from app.modules.promotions.router import router as promotions_router

# Усе бізнес-API живе під /api/v1. Новий модуль підключається одним рядком тут.
# (/health лежить поза версією: це перевірка інфраструктури, а не частина API.)
api_router = APIRouter(prefix='/api/v1')

api_router.include_router(locations_router)
api_router.include_router(menu_router)
api_router.include_router(promotions_router)
api_router.include_router(delivery_router)
api_router.include_router(allergens_router)
api_router.include_router(categories_router)
