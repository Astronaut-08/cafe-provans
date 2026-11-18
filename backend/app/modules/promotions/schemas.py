from datetime import date, time

from pydantic import BaseModel

from app.core.money import Money


class PromotionItemRead(BaseModel):
    dish_id: int
    name: str
    quantity: int
    unit_price: Money      # ціна однієї одиниці в цьому закладі
    is_available: bool


class PromotionRead(BaseModel):
    id: int
    title: str
    description: str | None
    price: Money                 # скільки платить гість: фіксована ціна акції або сума позицій
    items_total: Money           # скільки коштували б ті самі позиції окремо
    savings: Money               # items_total - price, якщо ціна акції вигідніша, інакше 0
    show_on_home: bool
    has_unavailable_items: bool  # лише коли pause_if_unavailable = false: акція видима, а частини немає
    start_time: time | None      # щоденне вікно дії (місцевий час закладу)
    end_time: time | None
    start_date: date | None
    end_date: date | None
    items: list[PromotionItemRead]
