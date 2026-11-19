import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(Base):
    """Довгий токен для отримання нових access-токенів без повторного введення пароля.

    У БД лежить лише SHA-256 від токена, а не сам токен: витік БД не дає зайти під чужим акаунтом.
    Кожне оновлення видає НОВИЙ токен, а старий відкликається (`revoked_at`). Токени одного входу
    (ланцюжок оновлень) мають спільний `family_id`. Якщо відкликаний токен прийшов вдруге, його
    або вкрали, або використали двічі, тож відкликається весь ланцюжок і вхід доведеться повторити.
    Час створення й завершення задає сервіс (а не БД), щоб логіку можна було тестувати з фіксованим часом.
    """
    __tablename__ = 'refresh_tokens'
    __table_args__ = (
        Index('ix_refresh_tokens_user_id', 'user_id'),
        Index('ix_refresh_tokens_family_id', 'family_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
