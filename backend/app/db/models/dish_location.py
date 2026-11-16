from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DishLocation(Base):
    """Доступність страви в конкретній локації. `price_override` NULL = беремо `dishes.price`."""
    __tablename__ = 'dish_locations'
    __table_args__ = (
        CheckConstraint('price_override IS NULL OR price_override >= 0', name='price_override_non_negative'),
        Index('idx_dish_locations_location_id', 'location_id'),
    )

    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id', ondelete='CASCADE'), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), primary_key=True)
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    price_override: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
