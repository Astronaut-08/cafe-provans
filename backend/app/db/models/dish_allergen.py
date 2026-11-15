from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from app.db.base import Base

class DishAllergen(Base):
    __tablename__ = 'dish_allergens'

    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id'), nullable=False, primary_key=True)
    allergen_id: Mapped[int] = mapped_column(ForeignKey('allergens.id'), nullable=False, primary_key=True)
    