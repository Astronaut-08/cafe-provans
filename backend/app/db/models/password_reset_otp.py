from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetOtp(Base):
    """Одноразовий код для відновлення пароля адміна («забув пароль»).

    Сам код (6 цифр) у БД не зберігається: лише HMAC від нього з ключем із налаштувань.
    Код діє обмежений час, має ліміт невдалих спроб (`attempts`) і використовується один раз (`used_at`).
    Перевіряється лише найновіший код користувача: новий запит скасовує попередні.
    """
    __tablename__ = 'password_reset_otps'
    __table_args__ = (
        Index('ix_password_reset_otps_user_id', 'user_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text('0'), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
