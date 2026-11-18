from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeliveryZoneArea(Base):
    """Що входить у зону доставки: ціле місто або одна вулиця міста. Список веде адміністратор.

    - `street = ''`: у зону входить усе місто (будь-яка вулиця);
    - `street = 'Шевченка'`: лише ця вулиця.
    Вулиця має перевагу над містом: якщо місто в жовтій зоні, а «Шевченка» у зеленій, то вулиця
    Шевченка зелена, решта міста жовта.

    Порожній рядок, а не NULL: так звичайний UNIQUE працює без винятків (NULL у UNIQUE не збігається
    з іншим NULL, і «ціле місто» можна було б додати двічі).

    Назви порівнюються після нормалізації (регістр, апострофи, «вул.», «м.»): див.
    app.modules.delivery.places. У БД лежить текст так, як його ввів адміністратор.
    """
    __tablename__ = 'delivery_zone_areas'
    __table_args__ = (
        # (zone_id, location_id) мусять вказувати на ту саму зону: адреса не може потрапити в зону чужого закладу
        ForeignKeyConstraint(
            ['zone_id', 'location_id'], ['delivery_zones.id', 'delivery_zones.location_id'],
            ondelete='CASCADE', name='fk_delivery_zone_areas_zone_location',
        ),
        UniqueConstraint('location_id', 'city', 'street', name='uq_delivery_zone_areas_place'),
        CheckConstraint("btrim(city) <> ''", name='city_not_blank'),
        # вулиця з самих пробілів після нормалізації стала б порожньою, тобто мовчки «цілим містом»
        CheckConstraint('street = btrim(street)', name='street_trimmed'),
        Index('ix_delivery_zone_areas_zone_id', 'zone_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), nullable=False)
    zone_id: Mapped[int] = mapped_column(nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    street: Mapped[str] = mapped_column(String(150), server_default='', nullable=False)
