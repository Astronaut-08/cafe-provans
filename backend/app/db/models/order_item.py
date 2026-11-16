from decimal import Decimal

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderItem(Base):
    """Позиція замовлення: або страва, або акція (рівно одне з `dish_id` / `promotion_id`).

    Страви не видаляємо (ON DELETE RESTRICT), а знімаємо з продажу через `is_available`.
    `name` і `unit_price` фіксуються на момент замовлення; `line_total` рахує сама БД.
    """
    __tablename__ = 'order_items'
    __table_args__ = (
        CheckConstraint(
            '(dish_id IS NOT NULL AND promotion_id IS NULL) OR (dish_id IS NULL AND promotion_id IS NOT NULL)',
            name='one_source',
        ),
        CheckConstraint('quantity > 0', name='quantity_positive'),
        CheckConstraint('unit_price >= 0', name='unit_price_non_negative'),
        Index('idx_order_items_order_id', 'order_id'),
        Index('idx_order_items_dish_id', 'dish_id'),
        Index('idx_order_items_promotion_id', 'promotion_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    dish_id: Mapped[int | None] = mapped_column(ForeignKey('dishes.id', ondelete='RESTRICT'), nullable=True)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey('promotions.id', ondelete='RESTRICT'), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(server_default=text('1'), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), Computed('unit_price * quantity', persisted=True), nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(250), nullable=True)
