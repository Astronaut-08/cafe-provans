from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerAddress(Base):
    __tablename__ = 'customer_addresses'
    __table_args__ = (
        Index('idx_customer_addresses_customer_id', 'customer_id'),
        # не більше однієї адреси «за замовчуванням» на гостя
        Index(
            'uq_customer_addresses_one_default', 'customer_id',
            unique=True,
            postgresql_where=text('is_default'),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(250), nullable=True)  # під'їзд, поверх, домофон
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text('false'), nullable=False)
