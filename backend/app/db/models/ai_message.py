from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import MessageRole, pg_enum


class AiMessage(Base):
    """Історія повідомлень для дебагу та аудиту ескалацій. Тільки додаємо, не редагуємо.
    `meta`: виклики інструментів, токени, модель.
    """
    __tablename__ = 'ai_messages'
    __table_args__ = (
        Index('idx_ai_messages_dialog_created', 'dialog_id', 'created_at'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey('ai_dialogs.id', ondelete='CASCADE'), nullable=False)
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, 'message_role'), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
