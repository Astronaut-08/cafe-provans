from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import OrderStatus, pg_enum


class OrderStatusHistory(Base):
    """Журнал змін статусу. `changed_by` NULL = система або AI."""
    __tablename__ = 'order_status_history'
    __table_args__ = (
        Index('idx_order_status_history_order_created', 'order_id', 'created_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(pg_enum(OrderStatus, 'order_status'), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(250), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
