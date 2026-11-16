from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import PaymentStatus, pg_enum


class Payment(Base):
    """Платіж по замовленню. Зараз лише готівка: provider = 'cash', external_id порожній.
    Онлайн-провайдер додасться без зміни схеми (external_id = id транзакції, raw_payload = вебхук).
    """
    __tablename__ = 'payments'
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name='uq_payments_provider_external_id'),
        CheckConstraint('amount > 0', name='amount_positive'),
        Index('idx_payments_order_id', 'order_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='RESTRICT'), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, 'payment_status'), server_default='pending', nullable=False,
    )
    raw_payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
