"""Правила ціни та доступності страви в закладі. Окремо від запитів, щоб меню й акції
рахували однаково (одне місце істини) і щоб правила легко тестувалися без БД.
"""
from decimal import Decimal


def effective_price(base_price: Decimal, price_override: Decimal | None) -> Decimal:
    """Ціна страви в закладі: своя ціна закладу (`dish_locations.price_override`),
    якщо вона задана, інакше базова ціна страви. Нуль це валідна ціна (безкоштовний соус), не «немає»."""
    return base_price if price_override is None else price_override


def is_dish_available(dish_available: bool, location_available: bool | None) -> bool:
    """Страву можна замовити, якщо вона не знята з продажу глобально (`dishes.is_available`)
    І доступна в цьому закладі (`dish_locations.is_available`).
    `location_available is None` означає, що в закладі страви немає взагалі (запису в dish_locations нема).
    """
    return dish_available and bool(location_available)
