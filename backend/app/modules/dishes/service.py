"""Керування стравами для адміна (меню: що продаємо, за якою ціною, де, з якими алергенами, з яким фото)
і стоп-лист закладу для офіціанта. Правила сервісів див. у modules/categories/service.py.

Читання меню для гостей живе в modules/menu, а тут лише керування.
"""
from collections import defaultdict
from collections.abc import Sequence

from fastapi import Depends, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.media import clear_image, delete_image, read_image_upload, replace_image
from app.db.enums import UserRole
from app.db.models.allergen import Allergen
from app.db.models.category import Category
from app.db.models.dish import Dish
from app.db.models.dish_allergen import DishAllergen
from app.db.models.dish_location import DishLocation
from app.db.models.location import Location
from app.db.models.user import User
from app.dependencies import get_db
from app.modules.allergens.schemas import AllergenRead
from app.modules.dishes.schemas import (
    DishAdminRead, DishCreate, DishLocationRead, DishLocationWrite, DishUpdate,
)


def _translate_integrity_error(exc: IntegrityError) -> Exception:
    # Postgres пише назву порушеного обмеження в текст помилки: за нею визначаємо, що саме не так.
    # Ці перевірки захищають і від гонки двох запитів (на відміну від попереднього select «чи існує»).
    text = str(exc.orig)
    if 'fk_dishes_category_id_categories' in text:
        return UnprocessableError('Категорію не знайдено', code='category_not_found')
    if 'fk_dish_allergens_allergen_id_allergens' in text:
        return UnprocessableError('Алерген не знайдено', code='allergen_not_found')
    if 'fk_dish_locations_location_id_locations' in text:
        return UnprocessableError('Заклад не знайдено', code='location_not_found')
    if 'fk_order_items_dish_id_dishes' in text or 'fk_promotion_items_dish_id_dishes' in text:
        return ConflictError(
            'Страву не можна видалити: вона є в замовленнях або акціях. '
            'Зніміть її з продажу (is_available: false) або приберіть із закладів',
            code='dish_in_use',
        )
    return exc


class DishService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- читання ----------

    async def _get_dish(self, dish_id: int) -> Dish:
        dish = await self.session.get(Dish, dish_id)
        if dish is None:
            raise NotFoundError('Страву не знайдено')
        return dish

    async def _to_read(self, dishes: Sequence[Dish]) -> list[DishAdminRead]:
        """Збирає повне подання страв: алергени й заклади для всіх страв двома запитами, а не по два на страву."""
        ids = [dish.id for dish in dishes]
        allergens: dict[int, list[AllergenRead]] = defaultdict(list)
        locations: dict[int, list[DishLocationRead]] = defaultdict(list)
        if ids:
            rows = await self.session.execute(
                select(DishAllergen.dish_id, Allergen)
                .join(Allergen, Allergen.id == DishAllergen.allergen_id)
                .where(DishAllergen.dish_id.in_(ids))
                .order_by(Allergen.name, Allergen.id)
            )
            for dish_id, allergen in rows:
                allergens[dish_id].append(AllergenRead.model_validate(allergen))
            rows = await self.session.scalars(
                select(DishLocation).where(DishLocation.dish_id.in_(ids)).order_by(DishLocation.location_id)
            )
            for row in rows:
                locations[row.dish_id].append(DishLocationRead.model_validate(row))
        return [
            DishAdminRead(
                id=d.id, category_id=d.category_id, name=d.name, description=d.description, price=d.price,
                weight=d.weight, diameter=d.diameter, image_url=d.image_url, badge=d.badge,
                is_available=d.is_available, show_on_home=d.show_on_home, created_at=d.created_at,
                allergens=allergens[d.id], locations=locations[d.id],
            )
            for d in dishes
        ]

    async def list(
        self, *, category_id: int | None, location_id: int | None, is_available: bool | None,
        limit: int, offset: int,
    ) -> list[DishAdminRead]:
        """Усі страви (навіть ті, що ніде не продаються): це робочий список адміна, а не меню для гостей."""
        stmt = select(Dish).join(Category, Category.id == Dish.category_id)
        if category_id is not None:
            stmt = stmt.where(Dish.category_id == category_id)
        if location_id is not None:
            stmt = stmt.where(
                Dish.id.in_(select(DishLocation.dish_id).where(DishLocation.location_id == location_id))
            )
        if is_available is not None:
            stmt = stmt.where(Dish.is_available == is_available)
        stmt = stmt.order_by(Category.sort_order, Category.name, Category.id, Dish.name, Dish.id)
        dishes = (await self.session.scalars(stmt.limit(limit).offset(offset))).all()
        return await self._to_read(dishes)

    async def get(self, dish_id: int) -> DishAdminRead:
        return (await self._to_read([await self._get_dish(dish_id)]))[0]

    # ---------- створення, зміна, видалення ----------

    async def create(self, data: DishCreate) -> DishAdminRead:
        dish = Dish(**data.model_dump(include={
            'category_id', 'name', 'price', 'description', 'weight', 'diameter', 'badge',
            'is_available', 'show_on_home',
        }))
        self.session.add(dish)
        try:
            await self.session.flush()  # потрібен dish.id для зв'язаних записів (і перевірка категорії)
            self.session.add_all(DishAllergen(dish_id=dish.id, allergen_id=a) for a in data.allergen_ids)
            if data.locations is None:
                # за замовчуванням у всіх наявних закладах (вимкнені теж: з'явиться, щойно заклад увімкнуть)
                location_ids = (await self.session.scalars(select(Location.id).order_by(Location.id))).all()
                assignments = [DishLocation(dish_id=dish.id, location_id=i) for i in location_ids]
            else:
                assignments = [
                    DishLocation(
                        dish_id=dish.id, location_id=item.location_id,
                        is_available=item.is_available, price_override=item.price_override,
                    )
                    for item in data.locations
                ]
            self.session.add_all(assignments)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _translate_integrity_error(exc)
        return await self.get(dish.id)

    async def update(self, dish_id: int, data: DishUpdate) -> DishAdminRead:
        dish = await self._get_dish(dish_id)
        changes = data.model_dump(exclude_unset=True)
        allergen_ids = changes.pop('allergen_ids', None)
        for field, value in changes.items():
            setattr(dish, field, value)
        try:
            if allergen_ids is not None:
                # набір алергенів замінюється повністю: старі прибираємо, нові додаємо
                await self.session.execute(delete(DishAllergen).where(DishAllergen.dish_id == dish.id))
                self.session.add_all(DishAllergen(dish_id=dish.id, allergen_id=a) for a in allergen_ids)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _translate_integrity_error(exc)
        return await self.get(dish.id)

    async def delete(self, dish_id: int) -> None:
        dish = await self._get_dish(dish_id)
        image_url = dish.image_url
        await self.session.delete(dish)  # алергени й заклади страви БД видаляє каскадом
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _translate_integrity_error(exc)
        await delete_image(image_url)

    # ---------- страва в закладі ----------

    async def put_location(self, dish_id: int, location_id: int, data: DishLocationWrite) -> DishLocationRead:
        """Додає страву в заклад або повністю перезаписує її запис там (PUT): ціна закладу й доступність."""
        await self._get_dish(dish_id)
        if await self.session.get(Location, location_id) is None:
            raise NotFoundError('Заклад не знайдено')
        values = dict(is_available=data.is_available, price_override=data.price_override)
        row = (await self.session.execute(
            insert(DishLocation).values(dish_id=dish_id, location_id=location_id, **values)
            .on_conflict_do_update(index_elements=['dish_id', 'location_id'], set_=values)
            .returning(DishLocation)
        )).scalar_one()
        result = DishLocationRead.model_validate(row)
        await self.session.commit()
        return result

    async def remove_location(self, dish_id: int, location_id: int) -> None:
        """Прибирає страву з меню закладу (історія замовлень не зачіпається)."""
        removed = await self.session.execute(
            delete(DishLocation).where(DishLocation.dish_id == dish_id, DishLocation.location_id == location_id)
            .returning(DishLocation.dish_id)
        )
        if removed.first() is None:
            raise NotFoundError('Цієї страви немає в меню закладу')
        await self.session.commit()

    async def set_availability(
        self, actor: User, location_id: int, dish_id: int, is_available: bool,
    ) -> DishLocationRead:
        """Стоп-лист: вмикає/вимикає страву в закладі. Офіціант керує лише СВОЇМ закладом, адмін будь-яким."""
        if actor.role is not UserRole.admin:
            if actor.location_id is None:
                raise ForbiddenError('Вас не прив\'язано до закладу, зверніться до адміністратора', code='no_location')
            if actor.location_id != location_id:
                raise ForbiddenError('Можна змінювати лише страви свого закладу', code='other_location')
        row = (await self.session.execute(
            update(DishLocation)
            .where(DishLocation.dish_id == dish_id, DishLocation.location_id == location_id)
            .values(is_available=is_available)
            .returning(DishLocation)
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundError('Цієї страви немає в меню закладу')
        result = DishLocationRead.model_validate(row)
        await self.session.commit()
        return result

    # ---------- фото ----------

    async def set_image(self, dish_id: int, file: UploadFile) -> DishAdminRead:
        dish = await self._get_dish(dish_id)
        data, extension = await read_image_upload(file)
        await replace_image(self.session, dish, 'dishes', data, extension)
        return await self.get(dish.id)

    async def remove_image(self, dish_id: int) -> DishAdminRead:
        dish = await self._get_dish(dish_id)
        await clear_image(self.session, dish)
        return await self.get(dish.id)


def get_dish_service(session: AsyncSession = Depends(get_db)) -> DishService:
    return DishService(session)
