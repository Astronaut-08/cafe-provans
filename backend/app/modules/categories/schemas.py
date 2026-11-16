"""Схеми модуля. Трійка Create / Update / Read: стандартний шаблон для кожного модуля.

- Create: що клієнт надсилає при створенні (extra='forbid': одруківка в полі це помилка, а не мовчазне ігнорування).
- Update: усі поля необов'язкові (PATCH); змінюється лише те, що клієнт прислав.
- Read: що віддаємо клієнту; `from_attributes` дозволяє будувати його прямо з ORM-обʼєкта.
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: CategoryName
    sort_order: int = Field(default=0, ge=0, le=1_000_000)


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: CategoryName | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode='after')
    def forbid_explicit_null(self) -> 'CategoryUpdate':
        # «не передано» це нормально, а явний null означав би записати NULL у NOT NULL колонку
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f'Поле {field} не може бути null')
        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int
