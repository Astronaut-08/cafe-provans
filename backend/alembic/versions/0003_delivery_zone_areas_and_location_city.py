"""delivery zone areas and location city

Місто й посилання на карту в закладі; адреси зон доставки (ціле місто або вулиця), які веде адміністратор.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17 17:29:53.071799

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('locations', sa.Column('city', sa.String(length=100), nullable=True))
    op.add_column('locations', sa.Column('delivery_map_url', sa.String(length=500), nullable=True))

    # Спершу унікальність (id, location_id): саме на неї посилається складений ключ таблиці адрес.
    op.create_unique_constraint('uq_delivery_zones_id_location_id', 'delivery_zones', ['id', 'location_id'])

    op.create_table(
        'delivery_zone_areas',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('zone_id', sa.Integer(), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=False),
        sa.Column('street', sa.String(length=150), server_default='', nullable=False),
        sa.CheckConstraint("btrim(city) <> ''", name=op.f('ck_delivery_zone_areas_city_not_blank')),
        sa.CheckConstraint('street = btrim(street)', name=op.f('ck_delivery_zone_areas_street_trimmed')),
        sa.ForeignKeyConstraint(
            ['location_id'], ['locations.id'],
            name=op.f('fk_delivery_zone_areas_location_id_locations'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['zone_id', 'location_id'], ['delivery_zones.id', 'delivery_zones.location_id'],
            name='fk_delivery_zone_areas_zone_location', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_zone_areas')),
        sa.UniqueConstraint('location_id', 'city', 'street', name='uq_delivery_zone_areas_place'),
    )
    op.create_index('ix_delivery_zone_areas_zone_id', 'delivery_zone_areas', ['zone_id'], unique=False)


def downgrade() -> None:
    # у зворотному порядку: таблиця адрес тримає посилання на унікальність зон
    op.drop_index('ix_delivery_zone_areas_zone_id', table_name='delivery_zone_areas')
    op.drop_table('delivery_zone_areas')
    op.drop_constraint('uq_delivery_zones_id_location_id', 'delivery_zones', type_='unique')
    op.drop_column('locations', 'delivery_map_url')
    op.drop_column('locations', 'city')
