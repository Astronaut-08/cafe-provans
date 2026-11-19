"""Допоміжні функції для підготовки даних у тестах (замість громіздких фікстур).

Кожна функція додає запис і робить commit: commit сесії тесту лише «відпускає» savepoint, тож
дані видно запитам API, а в кінці тесту зовнішня транзакція все відкочує.
"""
import functools
from datetime import UTC, date, datetime, time
from decimal import Decimal

from app.core.security import hash_password
from app.core.tokens import create_access_token
from app.db.enums import PromotionStatus, UserRole
from app.db.models.allergen import Allergen
from app.db.models.category import Category
from app.db.models.delivery_zone import DeliveryZone
from app.db.models.delivery_zone_area import DeliveryZoneArea
from app.db.models.dish import Dish
from app.db.models.dish_allergen import DishAllergen
from app.db.models.dish_location import DishLocation
from app.db.models.location import Location
from app.db.models.promotion import Promotion
from app.db.models.promotion_item import PromotionItem
from app.db.models.promotion_location import PromotionLocation
from app.db.models.user import User


async def make_location(
    db, name='Provans', *, active=True, opening: time | None = None, closing: time | None = None,
    timezone='Europe/Kyiv', address=None, city=None, map_url=None,
) -> Location:
    location = Location(
        name=name, is_active=active, opening_time=opening, closing_time=closing,
        timezone=timezone, address=address, city=city, delivery_map_url=map_url,
    )
    db.add(location)
    await db.commit()
    return location


async def make_category(db, name='Піца', sort_order=0) -> Category:
    category = Category(name=name, sort_order=sort_order)
    db.add(category)
    await db.commit()
    return category


async def make_dish(
    db, category: Category, name='Маргарита', price='200.00', *, available=True, home=False,
    sell_in: list[Location] | None = None, weight=None, description=None,
) -> Dish:
    """`sell_in`: у яких закладах страва продається (запис dish_locations, доступна й без знижки)."""
    dish = Dish(
        category_id=category.id, name=name, price=Decimal(price), is_available=available,
        show_on_home=home, weight=weight, description=description,
    )
    db.add(dish)
    await db.flush()
    for location in sell_in or []:
        db.add(DishLocation(dish_id=dish.id, location_id=location.id))
    await db.commit()
    return dish


async def set_dish_location(db, dish: Dish, location: Location, *, available=True, price_override=None) -> None:
    link = await db.get(DishLocation, (dish.id, location.id))
    if link is None:
        link = DishLocation(dish_id=dish.id, location_id=location.id)
        db.add(link)
    link.is_available = available
    link.price_override = None if price_override is None else Decimal(price_override)
    await db.commit()


async def make_allergen(db, code='gluten', name='Глютен') -> Allergen:
    allergen = Allergen(code=code, name=name)
    db.add(allergen)
    await db.commit()
    return allergen


async def add_allergen(db, dish: Dish, allergen: Allergen) -> None:
    db.add(DishAllergen(dish_id=dish.id, allergen_id=allergen.id))
    await db.commit()


async def make_promotion(
    db, title='Піца + напій', *, locations: list[Location] | None = None,
    items: list[tuple[Dish, int]] | None = None, price: str | None = None,
    status=PromotionStatus.active, start_time: time | None = None, end_time: time | None = None,
    start_date: date | None = None, end_date: date | None = None,
    home=False, pause_if_unavailable=True,
) -> Promotion:
    """`price=None`: ціна рахується як сума позицій (auto_calculate_price), інакше фіксована."""
    promotion = Promotion(
        title=title, status=status, show_on_home=home, pause_if_unavailable=pause_if_unavailable,
        custom_price=None if price is None else Decimal(price), auto_calculate_price=price is None,
        start_time=start_time, end_time=end_time, start_date=start_date, end_date=end_date,
    )
    db.add(promotion)
    await db.flush()
    for location in locations or []:
        db.add(PromotionLocation(promotion_id=promotion.id, location_id=location.id))
    for dish, quantity in items or []:
        db.add(PromotionItem(promotion_id=promotion.id, dish_id=dish.id, quantity=quantity))
    await db.commit()
    return promotion


def square(west: float, south: float, east: float, north: float) -> dict:
    """GeoJSON-прямокутник (координати [довгота, широта])."""
    return {'type': 'Polygon', 'coordinates': [
        [[west, south], [east, south], [east, north], [west, north], [west, south]],
    ]}


async def make_zone(
    db, location: Location, code='green', *, name=None, minimum='400', polygon: dict | None = None,
    sort_order=1, active=True, description=None,
) -> DeliveryZone:
    zone = DeliveryZone(
        location_id=location.id, code=code, name=name or code.capitalize(),
        min_order_amount=Decimal(minimum), polygon=polygon, sort_order=sort_order,
        is_active=active, description=description,
    )
    db.add(zone)
    await db.commit()
    return zone


async def make_area(db, zone: DeliveryZone, city: str, street: str = '') -> DeliveryZoneArea:
    """Що входить у зону. `street=''` означає «ціле місто» (так воно лежить у БД)."""
    area = DeliveryZoneArea(location_id=zone.location_id, zone_id=zone.id, city=city, street=street)
    db.add(area)
    await db.commit()
    return area


# ---------- персонал ----------

PASSWORD = 'Secret123'


@functools.cache
def _hash(password: str) -> str:
    # scrypt навмисно повільний; один хеш на пароль на весь прогін тестів, а не на кожного користувача
    return hash_password(password)


async def make_user(
    db, login='anna', password=PASSWORD, role=UserRole.waiter, *, active=True, email=None, full_name=None,
    must_change=False, locked_until=None, failed_attempts=0, phone=None, location=None, token_version=0,
) -> User:
    user = User(
        login=login, password_hash=_hash(password), full_name=full_name or login.capitalize(), role=role,
        is_active=active, email=email, must_change_password=must_change, locked_until=locked_until,
        failed_login_attempts=failed_attempts, phone=phone, location_id=location.id if location else None,
        token_version=token_version,
    )
    db.add(user)
    await db.commit()
    return user


def bearer(user: User, now: datetime | None = None) -> dict[str, str]:
    """Заголовок авторизації для користувача без реального входу (швидко). `now` має збігатися з set_now тесту."""
    token, _ = create_access_token(user.id, user.token_version, now or datetime.now(UTC))
    return {'Authorization': f'Bearer {token}'}
