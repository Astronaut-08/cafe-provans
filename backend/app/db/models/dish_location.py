from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Boolean, ForeignKey, Numeric
from decimal import Decimal
from app.db.base import Base

class DishLocation(Base):
    __tablename__ = 'dish_locations'

    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id'), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    price_override: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    