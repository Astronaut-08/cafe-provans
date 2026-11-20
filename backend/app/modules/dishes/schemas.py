"""Схеми керування стравами (для адміна). Трійка Create / Update / Read, як і в інших модулях.

Страва живе у двох місцях:
- сама страва (`dishes`): назва, категорія, базова ціна, опис, алергени, фото;
- страва в закладі (`dish_locations`): чи продається в цьому закладі, чи не в стоп-листі, власна ціна закладу.
Меню закладу гість бачить через GET /locations/{id}/menu, а тут адмін ним керує.
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.money import Money
from app.modules.allergens.schemas import AllergenRead

DishName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Ціна в гривнях, не більше двох знаків після коми. Стеля захищає від одруківки (18000 замість 180),
# нуль дозволений (безкоштовний соус).
Price = Annotated[Decimal, Field(ge=0, le=100_000, max_digits=10, decimal_places=2)]
Id = Annotated[int, Field(ge=1, le=2_147_483_647)]


def _blank_to_none(value):
    # з форми приходить "" замість «порожньо»: зберігаємо NULL, а не рядок із пробілів
    if isinstance(value, str) and not value.strip():
        return None
    return value


class DishLocationWrite(BaseModel):
    """PUT /dishes/{id}/locations/{location_id}: повний запис про страву в закладі (пропущена власна ціна = базова)."""
    model_config = ConfigDict(extra='forbid')

    is_available: bool = True
    price_override: Price | None = None


class DishLocationAssignment(DishLocationWrite):
    location_id: Id


class _DishFields(BaseModel):
    """Спільні правила для полів, які можна задати і при створенні, і при зміні."""
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    weight: int | None = Field(default=None, gt=0, le=100_000)      # грами
    diameter: int | None = Field(default=None, gt=0, le=200)        # сантиметри (піца)
    badge: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    _blank = field_validator('description', 'badge', mode='before')(_blank_to_none)


def _unique(ids: list[int]) -> list[int]:
    return list(dict.fromkeys(ids))  # без повторів, порядок збережено


class DishCreate(_DishFields):
    model_config = ConfigDict(extra='forbid')

    category_id: Id
    name: DishName
    price: Price
    is_available: bool = True        # false = знято з продажу в усіх закладах
    show_on_home: bool = False
    allergen_ids: list[Id] = Field(default_factory=list, max_length=50)
    # У яких закладах страва продається. Не передано = у всіх наявних закладах (зручно для мережі з кількома
    # однаковими меню). Порожній список [] = поки ні в одному (додасте пізніше через PUT /dishes/{id}/locations/...).
    locations: list[DishLocationAssignment] | None = Field(default=None, max_length=200)

    @field_validator('allergen_ids')
    @classmethod
    def _dedupe_allergens(cls, value: list[int]) -> list[int]:
        return _unique(value)

    @model_validator(mode='after')
    def _locations_unique(self) -> 'DishCreate':
        ids = [item.location_id for item in self.locations or []]
        if len(ids) != len(set(ids)):
            raise ValueError('Один заклад вказано кілька разів')
        return self


class DishUpdate(_DishFields):
    """PATCH: змінюється лише те, що передано. Описи/вагу/діаметр/значок можна очистити, передавши null.
    `allergen_ids`, якщо передано, ЗАМІНЮЄ весь набір алергенів страви. Фото змінюється окремо (POST /dishes/{id}/image),
    заклади окремо (PUT /dishes/{id}/locations/{location_id})."""
    model_config = ConfigDict(extra='forbid')

    category_id: Id | None = None
    name: DishName | None = None
    price: Price | None = None
    is_available: bool | None = None
    show_on_home: bool | None = None
    allergen_ids: list[Id] | None = Field(default=None, max_length=50)

    @field_validator('allergen_ids')
    @classmethod
    def _dedupe_allergens(cls, value: list[int] | None) -> list[int] | None:
        return None if value is None else _unique(value)

    @model_validator(mode='after')
    def _forbid_null_for_required(self) -> 'DishUpdate':
        # «не передано» нормально; явний null дозволений лише для полів, які можна очистити
        for field in ('category_id', 'name', 'price', 'is_available', 'show_on_home', 'allergen_ids'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'Поле {field} не може бути null')
        return self


class DishLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    is_available: bool
    price_override: Money | None   # null = у цьому закладі діє базова ціна страви


class DishAdminRead(BaseModel):
    id: int
    category_id: int
    name: str
    description: str | None
    price: Money                    # базова ціна; у закладі може бути своя (див. locations)
    weight: int | None
    diameter: int | None
    image_url: str | None
    badge: str | None
    is_available: bool
    show_on_home: bool
    created_at: datetime
    allergens: list[AllergenRead]
    locations: list[DishLocationRead]
