from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey, Enum as SQLEnum
from datetime import datetime, timezone
from enum import Enum
from app.db.base import Base

class UserRole(str, Enum):
    admin = 'admin'
    waiter = 'waiter'
    chef = 'chef'

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(70), nullable=False)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole, name='user_role'), default=UserRole.waiter, nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    