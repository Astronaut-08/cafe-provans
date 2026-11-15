from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String
from app.db.base import Base

class AiEscalationTrigger(Base):
    __tablename__ = 'ai_escalation_triggers'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ai_settings_id: Mapped[int] = mapped_column(ForeignKey('ai_settings.id'), nullable=False)
    trigger_text: Mapped[str] = mapped_column(String, nullable=False)
