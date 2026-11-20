"""Схеми замовлень (для персоналу): створення, зміна статусу, картка й рядок списку.

Ціни й суми тут НІКОЛИ не приходять від клієнта: у запиті лише що замовлено (id страви чи акції)
і скільки. Ціну, назву, суму й доставку рахує бекенд за даними закладу на момент замовлення.
"""
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator,
)

from app.core.money import Money
from app.core.phone import normalize_phone
from app.db.enums import FulfillmentType, OrderSource, OrderStatus, PaymentStatus

Id = Annotated[int, Field(ge=1, le=2_147_483_647)]
MAX_ITEM_LINES = 50      # скільки різних позицій у одному замовленні
MAX_QUANTITY = 50        # скільки штук однієї позиції


def _blank_to_none(value):
    # з форми приходить "" замість «порожньо»: зберігаємо NULL
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _phone(value: str) -> str:
    try:
        return normalize_phone(value)
    except ValueError as exc:
        raise ValueError(str(exc)) from None  # pydantic покаже текст у details без службового ланцюжка


Phone = Annotated[str, StringConstraints(max_length=30), AfterValidator(_phone)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=250)] | None
OptionalText = BeforeValidator(_blank_to_none)


class PaymentMethod(str, Enum):
    """Як гість заплатить. Обидва способи беруть гроші на місці; онлайн-оплата додасться пізніше."""
    cash = 'cash'          # готівка (у закладі чи кур'єру)
    terminal = 'terminal'  # картка через термінал (у закладі чи в кур'єра)


# ---------- запити ----------

class OrderItemCreate(BaseModel):
    """Одна позиція: рівно ОДНЕ з dish_id / promotion_id (страва або акція)."""
    model_config = ConfigDict(extra='forbid')

    dish_id: Id | None = None
    promotion_id: Id | None = None
    quantity: int = Field(1, ge=1, le=MAX_QUANTITY)
    note: Annotated[Note, OptionalText] = None   # побажання до позиції: «без цибулі»

    @model_validator(mode='after')
    def _exactly_one_source(self):
        if (self.dish_id is None) == (self.promotion_id is None):
            raise ValueError('Вкажіть рівно одне з dish_id або promotion_id')
        return self


class DeliveryAddress(BaseModel):
    """Адреса доставки. Зону визначають за містом і вулицею (як у /delivery/check-address); будинок лише для кур'єра."""
    model_config = ConfigDict(extra='forbid')

    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    street: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    building: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]   # будинок, кв.
    details: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, OptionalText,
    ] = None                                                                          # під'їзд, поверх, домофон

    def as_text(self) -> str:
        """Одним рядком для картки замовлення й кур'єра (копія на момент замовлення)."""
        text = f'{self.city}, {self.street}, {self.building}'
        return f'{text} ({self.details})' if self.details else text


class CustomerIn(BaseModel):
    model_config = ConfigDict(extra='forbid')

    phone: Phone
    full_name: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, OptionalText,
    ] = None


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    location_id: Id
    customer: CustomerIn
    fulfillment_type: FulfillmentType
    delivery: DeliveryAddress | None = None      # обов'язково для доставки, заборонено для самовивозу
    items: Annotated[list[OrderItemCreate], Field(min_length=1, max_length=MAX_ITEM_LINES)]
    payment_method: PaymentMethod
    staff_notes: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None, OptionalText,
    ] = None

    @model_validator(mode='after')
    def _delivery_matches_fulfillment(self):
        if self.fulfillment_type is FulfillmentType.delivery and self.delivery is None:
            raise ValueError('Для доставки потрібна адреса (delivery)')
        if self.fulfillment_type is FulfillmentType.pickup and self.delivery is not None:
            raise ValueError('Для самовивозу адреса (delivery) не потрібна')
        return self


class StatusChange(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: OrderStatus
    comment: Annotated[Note, OptionalText] = None   # причина скасування, уточнення для історії


class OrderNotesUpdate(BaseModel):
    """Нотатки персоналу (гість їх не бачить). null або порожній рядок очищає."""
    model_config = ConfigDict(extra='forbid')

    staff_notes: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None, OptionalText,
    ]


# ---------- відповіді ----------

class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_id: int | None
    promotion_id: int | None
    name: str
    unit_price: Money
    quantity: int
    line_total: Money
    note: str | None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    full_name: str | None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str          # cash / terminal
    amount: Money
    status: PaymentStatus
    created_at: datetime


class StaffBrief(BaseModel):
    id: int
    full_name: str


class StatusHistoryRead(BaseModel):
    status: OrderStatus
    comment: str | None
    changed_by: StaffBrief | None    # None = система або AI
    created_at: datetime


class ZoneRead(BaseModel):
    code: str
    name: str


class OrderRead(BaseModel):
    """Повна картка замовлення."""
    id: int
    order_number: str
    location_id: int
    source: OrderSource
    fulfillment_type: FulfillmentType
    status: OrderStatus
    payment_status: PaymentStatus
    delivery_zone: ZoneRead | None
    delivery_address: str | None
    subtotal_price: Money
    delivery_price: Money
    total_price: Money
    staff_notes: str | None
    created_at: datetime
    updated_at: datetime
    customer: CustomerRead
    items: list[OrderItemRead]
    payments: list[PaymentRead]
    history: list[StatusHistoryRead]
    # у які статуси ЦЕЙ працівник може перевести замовлення зараз: готові дані для кнопок
    allowed_statuses: list[OrderStatus]


class OrderListItem(BaseModel):
    """Рядок списку замовлень (без позицій і історії, щоб список був легким)."""
    id: int
    order_number: str
    location_id: int
    source: OrderSource
    fulfillment_type: FulfillmentType
    status: OrderStatus
    payment_status: PaymentStatus
    customer_name: str | None
    customer_phone: str
    delivery_address: str | None
    total_price: Money
    items_count: int            # скільки порцій усього (сума quantity)
    created_at: datetime
