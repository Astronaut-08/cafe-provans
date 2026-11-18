from pydantic import BaseModel, ConfigDict


class AllergenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str   # стабільний код (gluten, milk, ...) для іконок і фільтрів на фронтенді
    name: str
