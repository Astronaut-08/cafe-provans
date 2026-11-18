from datetime import date, datetime, time
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Index, Numeric, String, Text, Time, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import PromotionStatus, pg_enum


class Promotion(Base):
    """Акція. Ціна: або фіксована `custom_price`, або сума позицій (`auto_calculate_price`)."""
    __tablename__ = 'promotions'
    __table_args__ = (
        # рівно одне з двох: custom_price заповнене АБО auto_calculate_price = true
        CheckConstraint(
            '(custom_price IS NOT NULL AND auto_calculate_price = false) '
            'OR (custom_price IS NULL AND auto_calculate_price = true)',
            name='price_mode',
        ),
        CheckConstraint('custom_price IS NULL OR custom_price >= 0', name='custom_price_non_negative'),
        CheckConstraint('start_date IS NULL OR end_date IS NULL OR start_date <= end_date', name='dates_order'),
        Index(
            'idx_promotions_embedding', 'embedding',
            postgresql_using='hnsw',
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PromotionStatus] = mapped_column(
        pg_enum(PromotionStatus, 'promotion_status'), server_default='draft', nullable=False,
    )
    custom_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    auto_calculate_price: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    # годинне вікно дії (щодня) та період дат; NULL = без обмежень
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    show_on_home: Mapped[bool] = mapped_column(Boolean, server_default=text('false'), nullable=False)
    pause_if_unavailable: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    # NULL = embedding ще не порахований, тому акцію можна створити до генерації.
    # deferred: не вантажиться без явного запиту (див. Dish.embedding)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True, deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
