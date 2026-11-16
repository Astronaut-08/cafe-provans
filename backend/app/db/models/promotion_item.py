from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PromotionItem(Base):
    __tablename__ = 'promotion_items'
    __table_args__ = (
        UniqueConstraint('promotion_id', 'dish_id', name='uq_promotion_items_promotion_id_dish_id'),
        CheckConstraint('quantity > 0', name='quantity_positive'),
        Index('idx_promotion_items_dish_id', 'dish_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey('promotions.id', ondelete='CASCADE'), nullable=False)
    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id', ondelete='RESTRICT'), nullable=False)
    quantity: Mapped[int] = mapped_column(server_default=text('1'), nullable=False)
