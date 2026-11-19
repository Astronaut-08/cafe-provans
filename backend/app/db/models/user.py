from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import UserRole, pg_enum


class User(Base):
    """Тільки персонал. Гості живуть у `customers`.

    Вхід за логіном і паролем. Логін зберігається в нижньому регістрі
    (сервіс нормалізує його перед записом, CHECK це гарантує).
    Користувачів не видаляємо, а вимикаємо через `is_active`.

    Службові поля входу (клієнту не віддаються):
    - `token_version`: номер «покоління» токенів. Зміна пароля або скидання збільшує його, і всі раніше
      видані access-токени одразу перестають діяти (токен несе номер, з яким його видали);
    - `failed_login_attempts`, `locked_until`: захист від підбору пароля;
    - `must_change_password`: пароль задав адміністратор, тож працівник мусить замінити його власним.
    """
    __tablename__ = 'users'
    __table_args__ = (
        CheckConstraint('login = lower(login) AND char_length(login) >= 3', name='login_format'),
        CheckConstraint('email = lower(email)', name='email_lowercase'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(70), nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, 'user_role'), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id', ondelete='RESTRICT'), nullable=True)
    # Для відновлення пароля адміна (код надсилається сюди). Нижній регістр, як і логін.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text('false'), nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, server_default=text('0'), nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default=text('0'), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
