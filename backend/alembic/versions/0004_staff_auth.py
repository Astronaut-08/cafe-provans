"""staff auth: user login fields, refresh tokens, password reset otps

Вхід персоналу: email і службові поля в users (примусова зміна пароля, версія токенів, захист від
підбору пароля), таблиця refresh-токенів і таблиця одноразових кодів для відновлення пароля адміна.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18 09:07:31.210927

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Нові колонки мають server_default, тож наявні користувачі отримують безпечні значення:
    # без примусової зміни пароля, перша версія токенів, жодних невдалих спроб.
    op.add_column('users', sa.Column('email', sa.String(length=254), nullable=True))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(op.f('uq_users_email'), 'users', ['email'])
    # Alembic не бачить CHECK-обмежень сам, тож додаємо вручну (NULL проходить перевірку)
    op.create_check_constraint(op.f('ck_users_email_lowercase'), 'users', 'email = lower(email)')

    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash')),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)

    op.create_table(
        'password_reset_otps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_otps_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_otps')),
    )
    op.create_index('ix_password_reset_otps_user_id', 'password_reset_otps', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_password_reset_otps_user_id', table_name='password_reset_otps')
    op.drop_table('password_reset_otps')
    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_constraint(op.f('ck_users_email_lowercase'), 'users', type_='check')
    op.drop_constraint(op.f('uq_users_email'), 'users', type_='unique')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'email')
