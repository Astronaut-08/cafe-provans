from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Numeric, Date, Time, DateTime, Text, Enum as SQLEnum
from pgvector.sqlalchemy import Vector
from enum import Enum
from decimal import Decimal
from typing import List
from datetime import datetime, timezone, time, date
from app.db.base import Base

class PromotionStatus(str, Enum):
    draft = 'draft'
    active = 'active'
    paused = 'paused'
    archived = 'archived'

class Promotion(Base):
    __tablename__ = 'promotions'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PromotionStatus] = mapped_column(SQLEnum(PromotionStatus), default=PromotionStatus.draft, nullable=False)
    custom_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    auto_calculate_price: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=True)
    end_time: Mapped[time] = mapped_column(Time, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=True)
    show_on_home: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pause_if_unavailable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    