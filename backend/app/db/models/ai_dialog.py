from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import DialogStatus, pg_enum


class AiDialog(Base):
    """Діалог гостя з AI. Канал зараз один: `web` (чат на сайті), у `external_chat_id` лежить id сесії.

    `dialog_state` тримає лише компактний стан (кошик, поточний крок).
    `verified_by` / `verified_at` NULL = діалог ще не перевірила людина.
    """
    __tablename__ = 'ai_dialogs'
    __mapper_args__ = {'eager_defaults': True}
    __table_args__ = (
        CheckConstraint(
            '(verified_by IS NULL AND verified_at IS NULL) OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)',
            name='verified_pair',
        ),
        Index('idx_ai_dialogs_customer_created', 'customer_id', 'created_at'),
        Index('idx_ai_dialogs_channel_external', 'channel', 'external_chat_id'),
        Index('idx_ai_dialogs_location_status', 'location_id', 'status'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='RESTRICT'), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    external_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[DialogStatus] = mapped_column(
        pg_enum(DialogStatus, 'dialog_status'), server_default='active', nullable=False,
    )
    dialog_state: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
