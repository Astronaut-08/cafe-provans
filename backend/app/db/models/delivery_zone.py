from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeliveryZone(Base):
    """Зона доставки. Доставка безкоштовна, але діє мінімальна сума замовлення:
    зелена від 400 грн, жовта від 600, червона від 1000. Поза зонами лише самовивіз.

    Перевірка `orders.subtotal_price >= min_order_amount` робиться в сервісі
    (між таблицями її не виразити CHECK-ом).
    """
    __tablename__ = 'delivery_zones'
    __table_args__ = (
        UniqueConstraint('location_id', 'code', name='uq_delivery_zones_location_id_code'),
        # потрібен як ціль складеного зовнішнього ключа з delivery_zone_areas (зона й заклад мають збігатися)
        UniqueConstraint('id', 'location_id', name='uq_delivery_zones_id_location_id'),
        CheckConstraint('min_order_amount >= 0', name='min_order_amount_non_negative'),
        # у полі лежить лише GeoJSON-геометрія: сміття БД не прийме
        CheckConstraint(
            "polygon IS NULL OR (jsonb_typeof(polygon) = 'object' "
            "AND COALESCE(polygon->>'type', '') IN ('Polygon', 'MultiPolygon'))",
            name='polygon_geojson',
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id', ondelete='CASCADE'), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # green, yellow, red
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # які райони/вулиці входять у зону
    # Контур зони як GeoJSON (Polygon або MultiPolygon, координати [довгота, широта]),
    # імпортується з карти Google командою app.db.import_zones. NULL = контур ще не заданий,
    # така зона не знаходиться за координатами.
    # none_as_null: Python None це SQL NULL («контур ще не намальований»), а не JSON-значення null.
    # Без цього ORM писав би 'null', яке не NULL: ламає `polygon IS NOT NULL` і відхиляється CHECK-ом нижче.
    polygon: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text('true'), nullable=False)
    sort_order: Mapped[int] = mapped_column(server_default=text('0'), nullable=False)
