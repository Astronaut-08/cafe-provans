from pydantic import BaseModel

from app.core.money import Money


class AllergenBrief(BaseModel):
    code: str
    name: str


class MenuDish(BaseModel):
    id: int
    name: str
    description: str | None
    price: Money            # ціна в цьому закладі (власна ціна закладу або базова)
    weight: int | None      # грами
    diameter: int | None    # сантиметри (піца)
    image_url: str | None
    badge: str | None
    is_available: bool      # false = у стоп-листі: показуємо, але замовити не можна
    show_on_home: bool
    allergens: list[AllergenBrief]


class MenuCategory(BaseModel):
    id: int
    name: str
    sort_order: int
    dishes: list[MenuDish]


class MenuRead(BaseModel):
    location_id: int
    categories: list[MenuCategory]   # лише ті, у яких є страви цього закладу
