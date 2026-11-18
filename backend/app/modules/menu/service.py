from collections import defaultdict

from fastapi import Depends
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.allergen import Allergen
from app.db.models.category import Category
from app.db.models.dish import Dish
from app.db.models.dish_allergen import DishAllergen
from app.db.models.dish_location import DishLocation
from app.dependencies import get_db
from app.modules.menu.pricing import effective_price, is_dish_available
from app.modules.menu.schemas import AllergenBrief, MenuCategory, MenuDish, MenuRead


class MenuService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_menu(
        self, location_id: int, *, available_only: bool = False, featured_only: bool = False,
    ) -> MenuRead:
        """Меню закладу: страви, що в ньому продаються (є запис у dish_locations), по категоріях.

        available_only: сховати страви зі стоп-листа; featured_only: лише ті, що для головної сторінки.
        Колонки вибираємо явно, а не `select(Dish)`: `embedding` (вектор із 1536 чисел) гостю не потрібен.
        """
        stmt = (
            select(
                Dish.id, Dish.name, Dish.description, Dish.price, Dish.weight, Dish.diameter,
                Dish.image_url, Dish.badge, Dish.show_on_home,
                Dish.is_available.label('dish_available'),
                DishLocation.is_available.label('location_available'),
                DishLocation.price_override,
                Category.id.label('category_id'),
                Category.name.label('category_name'),
                Category.sort_order.label('category_sort_order'),
            )
            .join(DishLocation, and_(DishLocation.dish_id == Dish.id, DishLocation.location_id == location_id))
            .join(Category, Category.id == Dish.category_id)
            .order_by(Category.sort_order, Category.name, Category.id, Dish.name, Dish.id)
        )
        if available_only:
            stmt = stmt.where(Dish.is_available, DishLocation.is_available)
        if featured_only:
            stmt = stmt.where(Dish.show_on_home)
        rows = (await self.session.execute(stmt)).all()

        allergens = await self._allergens_for([row.id for row in rows])

        categories: dict[int, MenuCategory] = {}  # dict зберігає порядок вставки, а він уже відсортований
        for row in rows:
            category = categories.setdefault(
                row.category_id,
                MenuCategory(id=row.category_id, name=row.category_name, sort_order=row.category_sort_order, dishes=[]),
            )
            category.dishes.append(MenuDish(
                id=row.id, name=row.name, description=row.description,
                price=effective_price(row.price, row.price_override),
                weight=row.weight, diameter=row.diameter, image_url=row.image_url, badge=row.badge,
                is_available=is_dish_available(row.dish_available, row.location_available),
                show_on_home=row.show_on_home,
                allergens=allergens.get(row.id, []),
            ))
        return MenuRead(location_id=location_id, categories=list(categories.values()))

    async def _allergens_for(self, dish_ids: list[int]) -> dict[int, list[AllergenBrief]]:
        if not dish_ids:
            return {}
        rows = await self.session.execute(
            select(DishAllergen.dish_id, Allergen.code, Allergen.name)
            .join(Allergen, Allergen.id == DishAllergen.allergen_id)
            .where(DishAllergen.dish_id.in_(dish_ids))
            .order_by(Allergen.name, Allergen.id)
        )
        result: dict[int, list[AllergenBrief]] = defaultdict(list)
        for dish_id, code, name in rows:
            result[dish_id].append(AllergenBrief(code=code, name=name))
        return result


def get_menu_service(session: AsyncSession = Depends(get_db)) -> MenuService:
    return MenuService(session)
