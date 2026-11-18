from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import Money


class AreaInfo(BaseModel):
    city: str
    street: str | None           # None = у зону входить усе місто


class ZoneInfo(BaseModel):
    code: str                    # green / yellow / red
    name: str
    min_order_amount: Money      # мінімальна сума замовлення для безкоштовної доставки в цю зону
    description: str | None
    has_area: bool               # false = контур зони для карти ще не завантажений (до перевірки за адресою не стосується)
    areas: list[AreaInfo]        # що входить у зону: міста й вулиці, які вніс адміністратор


class DeliveryInfo(BaseModel):
    delivery_price: Money        # зараз завжди 0: доставка безкоштовна, умова лише мінімальна сума
    map_url: str | None          # що вбудувати на сайті як карту зон (задає адміністратор), або None
    zones: list[ZoneInfo]        # від найближчої до найдальшої; поза зонами лише самовивіз


class DeliveryCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    lat: float = Field(ge=-90, le=90, description='Широта')
    lng: float = Field(ge=-180, le=180, description='Довгота')


class AddressCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    # лише вулиця, номер будинку не потрібен (якщо його вписали, він ігнорується)
    street: Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)] | None = None


class ZoneBrief(BaseModel):
    code: str
    name: str
    min_order_amount: Money


class DeliveryCheck(BaseModel):
    deliverable: bool
    zone: ZoneBrief | None
    delivery_price: Money | None
    # якщо deliverable = false:
    #   outside_zones    адреси немає в жодній зоні, лише самовивіз
    #   not_configured   для закладу ще не внесено жодної зони (адрес або контурів), визначити неможливо
    #   street_required  місто є лише частинами (переліком вулиць): потрібна вулиця
    #   ambiguous_street вулиця без типу збігається з кількома («вул. Шевченка» і «пров. Шевченка») із різних зон:
    #                    треба попросити гостя уточнити тип або вибрати зі списку
    reason: Literal['outside_zones', 'not_configured', 'street_required', 'ambiguous_street'] | None = None
