from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiEscalationTrigger(Base):
    """Фраза або ситуація, коли діалог передається людині."""
    __tablename__ = 'ai_escalation_triggers'
    __table_args__ = (
        UniqueConstraint('ai_settings_id', 'trigger_text', name='uq_ai_escalation_triggers_ai_settings_id_trigger_text'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ai_settings_id: Mapped[int] = mapped_column(ForeignKey('ai_settings.id', ondelete='CASCADE'), nullable=False)
    trigger_text: Mapped[str] = mapped_column(String(255), nullable=False)
