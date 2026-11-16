from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Dish(Base):
    __tablename__ = 'dishes'
    __table_args__ = (
        CheckConstraint('price >= 0', name='price_non_negative'),
        CheckConstraint('weight IS NULL OR weight > 0', name='weight_positive'),
        CheckConstraint('diameter IS NULL OR diameter > 0', name='diameter_positive'),
        Index('idx_dishes_category_id', 'category_id'),
        Index(
            'idx_dishes_embedding', 'embedding',
            postgresql_using='hnsw',
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id', ondelete='RESTRICT'), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    weight: Mapped[int | None] = mapped_column(nullable=True)    # грами
    diameter: Mapped[int | None] = mapped_column(nullable=True)  # сантиметри (піца)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    badge: Mapped[str | None] = mapped_column(String(200), nullable=True)  # значок на картці
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    show_on_home: Mapped[bool] = mapped_column(Boolean, server_default=text('false'), nullable=False)
    # NULL = embedding ще не порахований
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
