from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Enum as SQLEnum, ForeignKey, Text, DateTime, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from datetime import datetime, timezone
from app.db.base import Base

class MessageRole(str, Enum):
    user = 'user'
    assistant = 'assistant'
    system = 'system'
    tool = 'tool'
    operator = 'operator'

class AiMessage(Base):
    __tablename__ = 'ai_messages'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey('ai_dialogs.id'), nullable=False)
    role: Mapped[MessageRole] = mapped_column(SQLEnum(MessageRole, name='message_role'), default=MessageRole.system, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | list] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
