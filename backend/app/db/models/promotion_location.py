from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PromotionLocation(Base):
    __tablename__ = 'promotion_locations'
    __table_args__ = (
        Index('idx_promotion_locations_location_id', 'location_id'),
    )

    promotion_id: Mapped[int] = mapped_column(ForeignKey('promotions.id', ondelete='CASCADE'), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), primary_key=True)
