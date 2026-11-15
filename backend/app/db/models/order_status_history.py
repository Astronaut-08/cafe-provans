from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String, DateTime, Enum as SQLEnum
from datetime import datetime, timezone
from order import OrderStatus
from app.db.base import Base

class OrderStatusHistory(Base):
    __tablename__ = 'order_status_history'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(SQLEnum(OrderStatus), default=OrderStatus.new, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=True)
    comment: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
