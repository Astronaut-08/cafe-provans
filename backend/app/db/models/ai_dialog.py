from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from enum import Enum
from app.db.base import Base

class DialogStatus(str, Enum):
    active = 'active'
    waiting_human = 'waiting_human'
    closed = 'closed'

class AiDialog(Base):
    __tablename__ = 'ai_dialogs'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    external_chat_id: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[DialogStatus] = mapped_column(SQLEnum(DialogStatus), default=DialogStatus.active, nullable=False)
    dialog_state: Mapped[dict | list] = mapped_column(JSONB, nullable=True)
    verified_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
