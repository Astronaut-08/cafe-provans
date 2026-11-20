"""Спільні декорації для тестів замовлень: два заклади, страви, зона доставки й працівники з токенами."""
from types import SimpleNamespace

from app.db.enums import UserRole
from tests.factories import (
    bearer, make_area, make_category, make_dish, make_location, make_user, make_zone, set_dish_location,
)


async def build_world(db, now) -> SimpleNamespace:
    """`now` має збігатися з set_now тесту: токени працівників видаються на цей момент."""
    w = SimpleNamespace()
    w.l1 = await make_location(db, 'Provans', city='Болехів')
    w.l2 = await make_location(db, 'Provans 2', city='Велика Турʼя')
    w.category = await make_category(db)

    w.pizza = await make_dish(db, w.category, 'Маргарита', '200.00', sell_in=[w.l1, w.l2])
    await set_dish_location(db, w.pizza, w.l2, price_override='250.00')   # у закладі 2 дорожче
    w.cola = await make_dish(db, w.category, 'Кола', '50.00', sell_in=[w.l1])
    w.pasta = await make_dish(db, w.category, 'Паста', '120.00', sell_in=[w.l2])        # лише в закладі 2
    w.off = await make_dish(db, w.category, 'Знята з продажу', '90.00', available=False, sell_in=[w.l1])
    w.stopped = await make_dish(db, w.category, 'У стоп-листі', '90.00', sell_in=[w.l1])
    await set_dish_location(db, w.stopped, w.l1, available=False)
    w.free = await make_dish(db, w.category, 'Безкоштовний соус', '0.00', sell_in=[w.l1])
    w.gold = await make_dish(db, w.category, 'Золота піца', '100000.00', sell_in=[w.l1])

    w.zone = await make_zone(db, w.l1, 'green', minimum='400')       # заклад 1: усе місто Болехів у зеленій зоні
    await make_area(db, w.zone, 'Болехів')

    w.admin = await make_user(db, 'admin1', role=UserRole.admin, full_name='Головний Адмін')
    w.waiter = await make_user(db, 'waiter1', role=UserRole.waiter, location=w.l1, full_name='Оля Офіціант')
    w.waiter2 = await make_user(db, 'waiter2', role=UserRole.waiter, location=w.l2, full_name='Іра Офіціант')
    w.waiter_free = await make_user(db, 'waiter3', role=UserRole.waiter, full_name='Без закладу')
    w.chef = await make_user(db, 'chef1', role=UserRole.chef, location=w.l1, full_name='Петро Кухар')
    w.chef2 = await make_user(db, 'chef2', role=UserRole.chef, location=w.l2, full_name='Кухар Два')

    w.h = SimpleNamespace(
        admin=bearer(w.admin, now), waiter=bearer(w.waiter, now), waiter2=bearer(w.waiter2, now),
        waiter_free=bearer(w.waiter_free, now), chef=bearer(w.chef, now), chef2=bearer(w.chef2, now),
    )
    return w


def pickup_payload(location_id, items, *, phone='0671234567', name=None, method='cash', **extra):
    """Тіло POST /orders для самовивозу. items: [(dish_id, quantity), ...]"""
    return {
        'location_id': location_id,
        'customer': {'phone': phone, 'full_name': name},
        'fulfillment_type': 'pickup',
        'items': [{'dish_id': dish_id, 'quantity': quantity} for dish_id, quantity in items],
        'payment_method': method,
        **extra,
    }


def delivery_payload(location_id, items, *, city='Болехів', street='вул. Шевченка', building='5', **extra):
    body = pickup_payload(location_id, items, **extra)
    body['fulfillment_type'] = 'delivery'
    body['delivery'] = {'city': city, 'street': street, 'building': building}
    return body
