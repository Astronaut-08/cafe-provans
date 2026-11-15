from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from app.db.base import Base

class PromotionLocation(Base):
    __tablename__ = 'promotion_locations'

    promotion_id: Mapped[int] = mapped_column(ForeignKey('promotions.id'), nullable=False, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False, primary_key=True)