from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import FulfillmentType, OrderSource, OrderStatus, PaymentStatus, pg_enum


class Order(Base):
    """Замовлення. Суми зафіксовані навмисно (денормалізація для фінансів).

    Правила, які БД гарантує: total = subtotal + delivery, а доставка потребує адреси та зони,
    самовивіз їх не має. Правила, які тримає сервіс у одній транзакції:
    - subtotal_price = сума order_items.line_total;
    - subtotal_price >= delivery_zones.min_order_amount для зони замовлення;
    - status = останній рядок order_status_history;
    - payment_status = підсумок за payments;
    - customer_id і location_id збігаються з ai_dialogs, якщо заповнений dialog_id.
    `source` і `fulfillment_type` без дефолту: їх завжди вказує код явно.
    """
    __tablename__ = 'orders'
    __mapper_args__ = {'eager_defaults': True}
    __table_args__ = (
        CheckConstraint('subtotal_price >= 0 AND delivery_price >= 0', name='prices_non_negative'),
        CheckConstraint('total_price = subtotal_price + delivery_price', name='total_matches_parts'),
        CheckConstraint(
            "(fulfillment_type = 'delivery' AND delivery_address IS NOT NULL AND delivery_zone_id IS NOT NULL) "
            "OR (fulfillment_type = 'pickup' AND delivery_address IS NULL AND delivery_zone_id IS NULL)",
            name='fulfillment_fields',
        ),
        Index('idx_orders_location_created', 'location_id', 'created_at'),
        Index('idx_orders_customer_created', 'customer_id', 'created_at'),
        Index('idx_orders_location_status', 'location_id', 'status'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='RESTRICT'), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    dialog_id: Mapped[int | None] = mapped_column(ForeignKey('ai_dialogs.id', ondelete='RESTRICT'), nullable=True)
    source: Mapped[OrderSource] = mapped_column(pg_enum(OrderSource, 'order_source'), nullable=False)
    fulfillment_type: Mapped[FulfillmentType] = mapped_column(
        pg_enum(FulfillmentType, 'fulfillment_type'), nullable=False,
    )
    delivery_zone_id: Mapped[int | None] = mapped_column(
        ForeignKey('delivery_zones.id', ondelete='RESTRICT'), nullable=True,
    )
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)  # копія адреси на момент замовлення
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, 'order_status'), server_default='new', nullable=False,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, 'payment_status'), server_default='unpaid', nullable=False,
    )
    subtotal_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    delivery_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text('0'), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    staff_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
