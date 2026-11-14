from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, Text, String, Boolean
from app.db.base import Base

class CustomerAddress(Base):
    __tablename__ = 'customer_addresses'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(String(250), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    