from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import structlog
from fastapi import Depends
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timewindow import to_local
from app.db.enums import PromotionStatus
from app.db.models.dish import Dish
from app.db.models.dish_location import DishLocation
from app.db.models.location import Location
from app.db.models.promotion import Promotion
from app.db.models.promotion_item import PromotionItem
from app.db.models.promotion_location import PromotionLocation
from app.dependencies import get_db
from app.modules.menu.pricing import effective_price, is_dish_available
from app.modules.promotions.rules import promotion_is_current
from app.modules.promotions.schemas import PromotionItemRead, PromotionRead

log = structlog.get_logger('app.promotions')


class PromotionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(
        self, location: Location, now: datetime, *, featured_only: bool = False,
    ) -> list[PromotionRead]:
        """Акції, які гість може побачити в закладі просто зараз.

        Акція показується, якщо: status = active; вона привʼязана до закладу (немає привʼязок =
        не діє ніде, адмін має обрати заклади явно); дата й час дії включають «зараз» за місцевим
        часом закладу; і, якщо стоїть pause_if_unavailable, усі її страви доступні в цьому закладі.
        """
        local_now = to_local(now, location.timezone)

        stmt = (
            select(
                Promotion.id, Promotion.title, Promotion.description, Promotion.custom_price,
                Promotion.start_time, Promotion.end_time, Promotion.start_date, Promotion.end_date,
                Promotion.show_on_home, Promotion.pause_if_unavailable,
            )
            .join(PromotionLocation, and_(
                PromotionLocation.promotion_id == Promotion.id, PromotionLocation.location_id == location.id,
            ))
            .where(Promotion.status == PromotionStatus.active)
            .order_by(Promotion.show_on_home.desc(), Promotion.id)
        )
        if featured_only:
            stmt = stmt.where(Promotion.show_on_home)

        candidates = [
            row for row in (await self.session.execute(stmt)).all()
            if promotion_is_current(
                start_date=row.start_date, end_date=row.end_date,
                start_time=row.start_time, end_time=row.end_time, local_now=local_now,
            )
        ]
        if not candidates:
            return []

        items = await self._items_for([row.id for row in candidates], location.id)

        result: list[PromotionRead] = []
        for row in candidates:
            promo_items = items.get(row.id, [])
            has_unavailable = any(not item.is_available for item in promo_items)
            if row.pause_if_unavailable and has_unavailable:
                continue

            items_total = sum((item.unit_price * item.quantity for item in promo_items), Decimal('0'))
            if row.custom_price is None and not promo_items:
                # ціна «сума позицій», а позицій немає: ціни не існує, ₴0 гостю показувати не можна
                log.warning('promotion_without_price', promotion_id=row.id)
                continue

            price = row.custom_price if row.custom_price is not None else items_total
            savings = max(items_total - price, Decimal('0')) if promo_items else Decimal('0')
            result.append(PromotionRead(
                id=row.id, title=row.title, description=row.description,
                price=price, items_total=items_total, savings=savings,
                show_on_home=row.show_on_home, has_unavailable_items=has_unavailable,
                start_time=row.start_time, end_time=row.end_time,
                start_date=row.start_date, end_date=row.end_date,
                items=promo_items,
            ))
        return result

    async def _items_for(self, promotion_ids: list[int], location_id: int) -> dict[int, list[PromotionItemRead]]:
        # outer join: страви може не бути в цьому закладі взагалі, тоді вона «недоступна», а не зникає з акції
        rows = await self.session.execute(
            select(
                PromotionItem.promotion_id, PromotionItem.quantity,
                Dish.id.label('dish_id'), Dish.name, Dish.price,
                Dish.is_available.label('dish_available'),
                DishLocation.is_available.label('location_available'),
                DishLocation.price_override,
            )
            .join(Dish, Dish.id == PromotionItem.dish_id)
            .outerjoin(DishLocation, and_(DishLocation.dish_id == Dish.id, DishLocation.location_id == location_id))
            .where(PromotionItem.promotion_id.in_(promotion_ids))
            .order_by(PromotionItem.promotion_id, PromotionItem.id)
        )
        result: dict[int, list[PromotionItemRead]] = defaultdict(list)
        for row in rows:
            result[row.promotion_id].append(PromotionItemRead(
                dish_id=row.dish_id, name=row.name, quantity=row.quantity,
                unit_price=effective_price(row.price, row.price_override),
                is_available=is_dish_available(row.dish_available, row.location_available),
            ))
        return result


def get_promotion_service(session: AsyncSession = Depends(get_db)) -> PromotionService:
    return PromotionService(session)
