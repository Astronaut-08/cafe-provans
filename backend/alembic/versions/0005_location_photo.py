"""location photo

Фото закладу для сайту: у БД лише адреса (/media/locations/...), сам файл лежить на диску сервера.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 09:01:22.810081

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('locations', sa.Column('image_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('locations', 'image_url')
