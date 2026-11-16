from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DishAllergen(Base):
    __tablename__ = 'dish_allergens'
    __table_args__ = (
        Index('idx_dish_allergens_allergen_id', 'allergen_id'),
    )

    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id', ondelete='CASCADE'), primary_key=True)
    allergen_id: Mapped[int] = mapped_column(ForeignKey('allergens.id', ondelete='CASCADE'), primary_key=True)
