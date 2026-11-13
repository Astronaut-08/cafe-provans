from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Time
from datetime import time
from app.db.base import Base

class Location(Base):
    __tablename__ = 'locations'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(70), nullable=False)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instagram: Mapped[str | None] = mapped_column(String(150), nullable=True)
    opening_time: Mapped[time] = mapped_column(Time)
    closing_time: Mapped[time] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(50), default='Europe/Kyiv', nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
