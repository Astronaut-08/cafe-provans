"""Бізнес-логіка модуля. Правила для всіх сервісів:

1. Сервіс не знає про HTTP: кидає NotFoundError / ConflictError / ..., а не HTTPException.
2. Сервіс володіє транзакцією: метод, що пише, закінчується `commit()`.
   Читальні методи нічого не комітять.
3. Очікувані порушення обмежень БД (FK, UNIQUE) ловимо тут і перетворюємо на ConflictError:
   попередня перевірка «чи існує» не захищає від гонки двох запитів, обмеження БД захищає.
"""
from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.category import Category
from app.dependencies import get_db
from app.modules.categories.schemas import CategoryCreate, CategoryUpdate


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> Sequence[Category]:
        result = await self.session.scalars(
            select(Category).order_by(Category.sort_order, Category.name, Category.id)
        )
        return result.all()

    async def get(self, category_id: int) -> Category:
        category = await self.session.get(Category, category_id)
        if category is None:
            raise NotFoundError('Категорію не знайдено')
        return category

    async def create(self, data: CategoryCreate) -> Category:
        category = Category(**data.model_dump())
        self.session.add(category)
        await self.session.commit()
        return category

    async def update(self, category_id: int, data: CategoryUpdate) -> Category:
        category = await self.get(category_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(category, field, value)
        await self.session.commit()
        return category

    async def delete(self, category_id: int) -> None:
        category = await self.get(category_id)
        await self.session.delete(category)
        try:
            await self.session.commit()
        except IntegrityError:
            # dishes.category_id має ON DELETE RESTRICT: категорію зі стравами видалити не можна
            await self.session.rollback()
            raise ConflictError('Не можна видалити категорію, у ній є страви', code='category_not_empty')


def get_category_service(session: AsyncSession = Depends(get_db)) -> CategoryService:
    return CategoryService(session)
