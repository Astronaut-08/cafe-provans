from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, ForeignKey, Numeric, DateTime, Text
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone
from decimal import Decimal
from typing import List
from app.db.base import Base

class Dish(Base):
    __tablename__ = 'dishes'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    weight: Mapped[int] = mapped_column(nullable=True)
    diameter: Mapped[int] = mapped_column(nullable=True)
    image_url: Mapped[str] = mapped_column(String(200), nullable=True)
    badge: Mapped[str] = mapped_column(String(200), nullable=True) # Значок
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    show_on_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
