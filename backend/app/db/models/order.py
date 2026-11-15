from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String, Numeric, Text, DateTime, Enum as SQLEnum
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from app.db.base import Base

class OrderSource(str, Enum):
    ai_chat = 'ai_chat'
    waiter = 'waiter'
    website = 'website'

class FulfillmentType(str, Enum):
    delivery = 'delivery'
    pickup = 'pickup'

class OrderStatus(str, Enum):
    new = 'new'
    confirmed = 'confirmed'
    preparing = 'preparing'
    ready = 'ready'
    out_of_delivery = 'out_of_delivery'
    completed = 'completed'
    cancelled = 'cancelled'

class PaymentStatus(str, Enum):
    unpaid = 'unpaid'
    pending = 'pending'
    paid = 'paid'
    failed = 'failed'
    refunded = 'refunded'

class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String, nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), nullable=False)
    dialog_id: Mapped[int] = mapped_column(ForeignKey('ai_dialogs.id'), nullable=True)
    source: Mapped[OrderSource] = mapped_column(SQLEnum(OrderSource, name='order_source' ), default=OrderSource.waiter, nullable=False)
    fulfillment_type: Mapped[FulfillmentType] = mapped_column(SQLEnum(FulfillmentType, name='fulfillment_type'), default=FulfillmentType.pickup, nullable=False)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(SQLEnum(OrderStatus, name='order_status', create_type=False), default=OrderStatus.new, nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus, name='payment_status', create_type=False), default=PaymentStatus.unpaid, nullable=False)
    subtotal_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    delivery_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    operator_notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
