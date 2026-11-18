from datetime import time

from sqlalchemy import Boolean, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Location(Base):
    __tablename__ = 'locations'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(70), nullable=False)
    # Усі заклади мережі називаються однаково (Provans), тож відрізняються лише містом і адресою.
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Посилання для показу карти зон на сайті (напр. вбудовування Google My Maps). Вносить адміністратор.
    delivery_map_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instagram: Mapped[str | None] = mapped_column(String(150), nullable=True)
    opening_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    closing_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), server_default='Europe/Kyiv', nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
