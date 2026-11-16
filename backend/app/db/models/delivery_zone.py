from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeliveryZone(Base):
    """Зона доставки. Доставка безкоштовна, але діє мінімальна сума замовлення:
    зелена від 400 грн, жовта від 600, червона від 1000. Поза зонами лише самовивіз.

    Перевірка `orders.subtotal_price >= min_order_amount` робиться в сервісі
    (між таблицями її не виразити CHECK-ом).
    """
    __tablename__ = 'delivery_zones'
    __table_args__ = (
        UniqueConstraint('location_id', 'code', name='uq_delivery_zones_location_id_code'),
        CheckConstraint('min_order_amount >= 0', name='min_order_amount_non_negative'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # green, yellow, red
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # які райони/вулиці входять у зону
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    sort_order: Mapped[int] = mapped_column(server_default=text('0'), nullable=False)
