"""delivery zone polygon

Контур зони доставки (GeoJSON Polygon/MultiPolygon) для визначення зони за координатами.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 22:45:19.299717

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('delivery_zones', sa.Column('polygon', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # Alembic не генерує CHECK для наявних таблиць, тому обмеження додаємо вручну
    # (ім'я збігається з тим, що дає naming_convention для моделі).
    # COALESCE обовʼязковий: для обʼєкта без ключа type `polygon->>'type'` це NULL, а CHECK
    # відхиляє лише FALSE, тож `NULL IN (...)` пропустило б сміття.
    op.create_check_constraint(
        op.f('ck_delivery_zones_polygon_geojson'),
        'delivery_zones',
        "polygon IS NULL OR (jsonb_typeof(polygon) = 'object' "
        "AND COALESCE(polygon->>'type', '') IN ('Polygon', 'MultiPolygon'))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_delivery_zones_polygon_geojson'), 'delivery_zones', type_='check')
    op.drop_column('delivery_zones', 'polygon')
