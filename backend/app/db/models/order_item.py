from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String, Numeric
from decimal import Decimal
from app.db.base import Base

class OrderItem(Base):
    __tablename__ = 'order_items'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), nullable=False)
    dish_id: Mapped[int] = mapped_column(ForeignKey('dishes.id'), nullable=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey('promotions.id'), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str] = mapped_column(String, nullable=True)
    