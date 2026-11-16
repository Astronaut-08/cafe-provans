from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiSetting(Base):
    """Налаштування AI-офіціанта: по одному рядку на локацію."""
    __tablename__ = 'ai_settings'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), unique=True, nullable=False)
    tone_of_voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_allergies: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    forward_allergies_to_human: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    require_guest_confirmation: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    escalation_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
