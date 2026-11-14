from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from app.db.base import Base

class PromotionItem(Base):
    __tablename__ = 'promotion_items'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey('promotions.id'), nullable=False)
    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id'), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    