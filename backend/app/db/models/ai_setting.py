from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String, Text, Boolean
from app.db.base import Base

class AiSetting(Base):
    __tablename__ = 'ai_settings'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False)
    tone_of_voice: Mapped[str] = mapped_column(Text, nullable=True)
    check_allergies: Mapped[bool] = mapped_column(Boolean, nullable=False)
    forward_allergies_to_human: Mapped[bool] = mapped_column(Boolean, nullable=False)
    require_guest_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    escalation_channel: Mapped[str] = mapped_column(String, nullable=True)
