"""Початкові дані. Запуск з папки backend:

    python -m app.db.seed           # лише обов'язкове: локація, зони доставки, алергени, налаштування AI
    python -m app.db.seed --demo    # + демо-меню для розробки (НЕ для продакшну)

Скрипт ідемпотентний: повторний запуск нічого не дублює і не перезаписує те, що адмін уже змінив.
Користувачів (персонал) тут немає: адміна створить команда з модуля auth (Фаза 4),
бо пароль має хешуватися тим самим кодом, яким потім перевіряється вхід.
"""
import argparse
import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AiEscalationTrigger, AiSetting, Allergen, Category, DeliveryZone, Dish, DishAllergen, DishLocation, Location,
)
from app.db.session import SessionLocal, engine

LOCATION_NAME = 'Provans'

# Доставка безкоштовна, але діє мінімальна сума замовлення залежно від зони.
# Що не входить у зони, те лише самовивіз. Опис зон (райони/вулиці) адмін заповнить сам.
DELIVERY_ZONES = [
    # code, назва, мінімальна сума (грн), порядок
    ('green', 'Зелена зона', Decimal('400'), 1),
    ('yellow', 'Жовта зона', Decimal('600'), 2),
    ('red', 'Червона зона', Decimal('1000'), 3),
]

# Стандартний перелік 14 алергенів (ЄС).
ALLERGENS = [
    ('gluten', 'Глютен'),
    ('crustaceans', 'Ракоподібні'),
    ('eggs', 'Яйця'),
    ('fish', 'Риба'),
    ('peanuts', 'Арахіс'),
    ('soy', 'Соя'),
    ('milk', 'Молоко та лактоза'),
    ('nuts', 'Горіхи'),
    ('celery', 'Селера'),
    ('mustard', 'Гірчиця'),
    ('sesame', 'Кунжут'),
    ('sulphites', 'Сульфіти'),
    ('lupin', 'Люпин'),
    ('molluscs', 'Молюски'),
]

# Фрази, після яких AI передає діалог людині. Адмін зможе редагувати список.
ESCALATION_TRIGGERS = ['алергія', 'скарга', 'повернення коштів', 'покличте менеджера', 'живу людину']

DEMO_MENU = {
    'Піца': [
        ('Маргарита', Decimal('180'), 'Томатний соус, моцарела, базилік.', ['gluten', 'milk']),
        ('Пепероні', Decimal('220'), 'Томатний соус, моцарела, пепероні.', ['gluten', 'milk']),
    ],
    'Салати': [
        ('Цезар з куркою', Decimal('190'), 'Курка, листя салату, пармезан, грінки, соус цезар.',
         ['gluten', 'milk', 'eggs', 'fish']),
    ],
    'Напої': [
        ('Домашній лимонад', Decimal('70'), 'Лимон, м\'ята, содова.', []),
    ],
}


async def seed_delivery_zones(s: AsyncSession, location_id: int) -> None:
    """Стандартні зелена/жовта/червона зони закладу з мінімальними сумами. Ідемпотентно: наявні зони й
    зміни адміністратора в них не чіпаємо. Викликається для кожного нового закладу (адмінка теж)."""
    await s.execute(
        insert(DeliveryZone).values([
            dict(location_id=location_id, code=code, name=name, min_order_amount=amount, sort_order=order)
            for code, name, amount, order in DELIVERY_ZONES
        ]).on_conflict_do_nothing(constraint='uq_delivery_zones_location_id_code')
    )


async def seed_required(s: AsyncSession) -> Location:
    # Усі заклади мережі називаються однаково (Provans), тож за назвою заклад не знайти: беремо перший за id.
    # Свій заклад створюємо лише на порожній БД; далі закладами керує адміністратор.
    location = (await s.execute(select(Location).order_by(Location.id).limit(1))).scalar_one_or_none()
    if location is None:
        # місто, адресу, телефон і години роботи адмін внесе сам: вигадувати їх не можна
        location = Location(name=LOCATION_NAME)
        s.add(location)
        await s.flush()

    # ON CONFLICT DO NOTHING: існуючі зони/алергени (і зміни адміна в них) не чіпаємо
    await seed_delivery_zones(s, location.id)
    await s.execute(
        insert(Allergen).values([dict(code=code, name=name) for code, name in ALLERGENS])
        .on_conflict_do_nothing(constraint='uq_allergens_code')
    )
    await s.execute(
        insert(AiSetting).values(location_id=location.id).on_conflict_do_nothing(constraint='uq_ai_settings_location_id')
    )
    ai_settings_id = (await s.execute(select(AiSetting.id).where(AiSetting.location_id == location.id))).scalar_one()
    await s.execute(
        insert(AiEscalationTrigger)
        .values([dict(ai_settings_id=ai_settings_id, trigger_text=t) for t in ESCALATION_TRIGGERS])
        .on_conflict_do_nothing(constraint='uq_ai_escalation_triggers_ai_settings_id_trigger_text')
    )
    return location


async def seed_demo(s: AsyncSession, location: Location) -> None:
    allergen_ids = dict((await s.execute(select(Allergen.code, Allergen.id))).all())
    for sort_order, (category_name, dishes) in enumerate(DEMO_MENU.items(), start=1):
        category = (await s.execute(select(Category).where(Category.name == category_name))).scalar_one_or_none()
        if category is None:
            category = Category(name=category_name, sort_order=sort_order)
            s.add(category)
            await s.flush()
        for name, price, description, allergens in dishes:
            exists = (await s.execute(
                select(Dish.id).where(Dish.category_id == category.id, Dish.name == name)
            )).scalar_one_or_none()
            if exists:
                continue
            dish = Dish(category_id=category.id, name=name, price=price, description=description)
            s.add(dish)
            await s.flush()
            s.add(DishLocation(dish_id=dish.id, location_id=location.id))
            s.add_all(DishAllergen(dish_id=dish.id, allergen_id=allergen_ids[code]) for code in allergens)


async def main(demo: bool) -> None:
    async with SessionLocal() as s:
        location = await seed_required(s)
        if demo:
            await seed_demo(s, location)
        await s.commit()
    await engine.dispose()
    print(f'seed ok (demo={"так" if demo else "ні"})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Початкові дані для БД')
    parser.add_argument('--demo', action='store_true', help='додати демо-меню (лише для розробки)')
    asyncio.run(main(parser.parse_args().demo))
