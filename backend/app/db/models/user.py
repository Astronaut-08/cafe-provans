from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import UserRole, pg_enum


class User(Base):
    """Тільки персонал. Гості живуть у `customers`.

    Вхід за логіном і паролем. Логін зберігається в нижньому регістрі
    (сервіс нормалізує його перед записом, CHECK це гарантує).
    Користувачів не видаляємо, а вимикаємо через `is_active`.
    """
    __tablename__ = 'users'
    __table_args__ = (
        CheckConstraint('login = lower(login) AND char_length(login) >= 3', name='login_format'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(70), nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, 'user_role'), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id', ondelete='RESTRICT'), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
