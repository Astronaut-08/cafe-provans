"""initial schema

Перша міграція: розширення pgvector, enum-типи, усі таблиці, індекси та CHECK-обмеження.
Enum-типи створюються тут один раз (у моделях стоїть create_type=False).

Revision ID: 0001
Revises: 
Create Date: 2026-11-15 19:10:39.985256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum-типи Postgres. Значення зафіксовані тут навмисно: міграція не залежить від коду застосунку.
user_role = postgresql.ENUM('admin', 'waiter', 'chef', name='user_role', create_type=False)
order_source = postgresql.ENUM('ai_chat', 'waiter', 'website', name='order_source', create_type=False)
fulfillment_type = postgresql.ENUM('delivery', 'pickup', name='fulfillment_type', create_type=False)
order_status = postgresql.ENUM('new', 'confirmed', 'preparing', 'ready', 'out_for_delivery', 'completed', 'cancelled', name='order_status', create_type=False)
payment_status = postgresql.ENUM('unpaid', 'pending', 'paid', 'failed', 'refunded', name='payment_status', create_type=False)
promotion_status = postgresql.ENUM('draft', 'active', 'paused', 'archived', name='promotion_status', create_type=False)
dialog_status = postgresql.ENUM('active', 'waiting_human', 'closed', name='dialog_status', create_type=False)
message_role = postgresql.ENUM('user', 'assistant', 'system', 'tool', 'staff', name='message_role', create_type=False)

ENUMS = [user_role, order_source, fulfillment_type, order_status, payment_status, promotion_status, dialog_status, message_role]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table('allergens',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_allergens')),
    sa.UniqueConstraint('code', name=op.f('uq_allergens_code'))
    )
    op.create_table('categories',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories'))
    )
    op.create_table('customers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('phone', name=op.f('uq_customers_phone'))
    )
    op.create_table('locations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=70), nullable=False),
    sa.Column('address', sa.String(length=200), nullable=True),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('instagram', sa.String(length=150), nullable=True),
    sa.Column('opening_time', sa.Time(), nullable=True),
    sa.Column('closing_time', sa.Time(), nullable=True),
    sa.Column('timezone', sa.String(length=50), server_default='Europe/Kyiv', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_locations'))
    )
    op.create_table('promotions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', promotion_status, server_default='draft', nullable=False),
    sa.Column('custom_price', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('auto_calculate_price', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('end_time', sa.Time(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('show_on_home', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('pause_if_unavailable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('embedding_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('embedding_content_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(custom_price IS NOT NULL AND auto_calculate_price = false) OR (custom_price IS NULL AND auto_calculate_price = true)', name=op.f('ck_promotions_price_mode')),
    sa.CheckConstraint('custom_price IS NULL OR custom_price >= 0', name=op.f('ck_promotions_custom_price_non_negative')),
    sa.CheckConstraint('start_date IS NULL OR end_date IS NULL OR start_date <= end_date', name=op.f('ck_promotions_dates_order')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promotions'))
    )
    op.create_index('idx_promotions_embedding', 'promotions', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('ai_settings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('tone_of_voice', sa.Text(), nullable=True),
    sa.Column('check_allergies', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('forward_allergies_to_human', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('require_guest_confirmation', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('escalation_channel', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_ai_settings_location_id_locations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_settings')),
    sa.UniqueConstraint('location_id', name=op.f('uq_ai_settings_location_id'))
    )
    op.create_table('customer_addresses',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('comment', sa.String(length=250), nullable=True),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_addresses_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_addresses'))
    )
    op.create_index('idx_customer_addresses_customer_id', 'customer_addresses', ['customer_id'], unique=False)
    op.create_index('uq_customer_addresses_one_default', 'customer_addresses', ['customer_id'], unique=True, postgresql_where=sa.text('is_default'))
    op.create_table('delivery_zones',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('min_order_amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint('min_order_amount >= 0', name=op.f('ck_delivery_zones_min_order_amount_non_negative')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_delivery_zones_location_id_locations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_zones')),
    sa.UniqueConstraint('location_id', 'code', name='uq_delivery_zones_location_id_code')
    )
    op.create_table('dishes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('weight', sa.Integer(), nullable=True),
    sa.Column('diameter', sa.Integer(), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('badge', sa.String(length=200), nullable=True),
    sa.Column('is_available', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('show_on_home', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('embedding_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('embedding_content_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('diameter IS NULL OR diameter > 0', name=op.f('ck_dishes_diameter_positive')),
    sa.CheckConstraint('price >= 0', name=op.f('ck_dishes_price_non_negative')),
    sa.CheckConstraint('weight IS NULL OR weight > 0', name=op.f('ck_dishes_weight_positive')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_dishes_category_id_categories'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dishes'))
    )
    op.create_index('idx_dishes_category_id', 'dishes', ['category_id'], unique=False)
    op.create_index('idx_dishes_embedding', 'dishes', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('promotion_locations',
    sa.Column('promotion_id', sa.Integer(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_promotion_locations_location_id_locations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], name=op.f('fk_promotion_locations_promotion_id_promotions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('promotion_id', 'location_id', name=op.f('pk_promotion_locations'))
    )
    op.create_index('idx_promotion_locations_location_id', 'promotion_locations', ['location_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('login', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('full_name', sa.String(length=70), nullable=False),
    sa.Column('role', user_role, nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('login = lower(login) AND char_length(login) >= 3', name=op.f('ck_users_login_format')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_users_location_id_locations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('login', name=op.f('uq_users_login')),
    sa.UniqueConstraint('phone', name=op.f('uq_users_phone'))
    )
    op.create_table('ai_dialogs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('external_chat_id', sa.String(length=100), nullable=True),
    sa.Column('status', dialog_status, server_default='active', nullable=False),
    sa.Column('dialog_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('verified_by', sa.Integer(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(verified_by IS NULL AND verified_at IS NULL) OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)', name=op.f('ck_ai_dialogs_verified_pair')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_ai_dialogs_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_ai_dialogs_location_id_locations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['verified_by'], ['users.id'], name=op.f('fk_ai_dialogs_verified_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_dialogs'))
    )
    op.create_index('idx_ai_dialogs_channel_external', 'ai_dialogs', ['channel', 'external_chat_id'], unique=False)
    op.create_index('idx_ai_dialogs_customer_created', 'ai_dialogs', ['customer_id', 'created_at'], unique=False)
    op.create_index('idx_ai_dialogs_location_status', 'ai_dialogs', ['location_id', 'status'], unique=False)
    op.create_table('ai_escalation_triggers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ai_settings_id', sa.Integer(), nullable=False),
    sa.Column('trigger_text', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['ai_settings_id'], ['ai_settings.id'], name=op.f('fk_ai_escalation_triggers_ai_settings_id_ai_settings'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_escalation_triggers')),
    sa.UniqueConstraint('ai_settings_id', 'trigger_text', name='uq_ai_escalation_triggers_ai_settings_id_trigger_text')
    )
    op.create_table('dish_allergens',
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('allergen_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['allergen_id'], ['allergens.id'], name=op.f('fk_dish_allergens_allergen_id_allergens'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], name=op.f('fk_dish_allergens_dish_id_dishes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dish_id', 'allergen_id', name=op.f('pk_dish_allergens'))
    )
    op.create_index('idx_dish_allergens_allergen_id', 'dish_allergens', ['allergen_id'], unique=False)
    op.create_table('dish_locations',
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('is_available', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('price_override', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.CheckConstraint('price_override IS NULL OR price_override >= 0', name=op.f('ck_dish_locations_price_override_non_negative')),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], name=op.f('fk_dish_locations_dish_id_dishes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_dish_locations_location_id_locations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dish_id', 'location_id', name=op.f('pk_dish_locations'))
    )
    op.create_index('idx_dish_locations_location_id', 'dish_locations', ['location_id'], unique=False)
    op.create_table('promotion_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('promotion_id', sa.Integer(), nullable=False),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_promotion_items_quantity_positive')),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], name=op.f('fk_promotion_items_dish_id_dishes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], name=op.f('fk_promotion_items_promotion_id_promotions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promotion_items')),
    sa.UniqueConstraint('promotion_id', 'dish_id', name='uq_promotion_items_promotion_id_dish_id')
    )
    op.create_index('idx_promotion_items_dish_id', 'promotion_items', ['dish_id'], unique=False)
    op.create_table('ai_messages',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('dialog_id', sa.Integer(), nullable=False),
    sa.Column('role', message_role, nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dialog_id'], ['ai_dialogs.id'], name=op.f('fk_ai_messages_dialog_id_ai_dialogs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages'))
    )
    op.create_index('idx_ai_messages_dialog_created', 'ai_messages', ['dialog_id', 'created_at'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_number', sa.String(length=30), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('dialog_id', sa.Integer(), nullable=True),
    sa.Column('source', order_source, nullable=False),
    sa.Column('fulfillment_type', fulfillment_type, nullable=False),
    sa.Column('delivery_zone_id', sa.Integer(), nullable=True),
    sa.Column('delivery_address', sa.Text(), nullable=True),
    sa.Column('status', order_status, server_default='new', nullable=False),
    sa.Column('payment_status', payment_status, server_default='unpaid', nullable=False),
    sa.Column('subtotal_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('delivery_price', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('staff_notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(fulfillment_type = 'delivery' AND delivery_address IS NOT NULL AND delivery_zone_id IS NOT NULL) OR (fulfillment_type = 'pickup' AND delivery_address IS NULL AND delivery_zone_id IS NULL)", name=op.f('ck_orders_fulfillment_fields')),
    sa.CheckConstraint('subtotal_price >= 0 AND delivery_price >= 0', name=op.f('ck_orders_prices_non_negative')),
    sa.CheckConstraint('total_price = subtotal_price + delivery_price', name=op.f('ck_orders_total_matches_parts')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_orders_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['delivery_zone_id'], ['delivery_zones.id'], name=op.f('fk_orders_delivery_zone_id_delivery_zones'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dialog_id'], ['ai_dialogs.id'], name=op.f('fk_orders_dialog_id_ai_dialogs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_orders_location_id_locations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('order_number', name=op.f('uq_orders_order_number'))
    )
    op.create_index('idx_orders_customer_created', 'orders', ['customer_id', 'created_at'], unique=False)
    op.create_index('idx_orders_location_created', 'orders', ['location_id', 'created_at'], unique=False)
    op.create_index('idx_orders_location_status', 'orders', ['location_id', 'status'], unique=False)
    op.create_table('order_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('dish_id', sa.Integer(), nullable=True),
    sa.Column('promotion_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=10, scale=2), sa.Computed('unit_price * quantity', persisted=True), nullable=False),
    sa.Column('note', sa.String(length=250), nullable=True),
    sa.CheckConstraint('(dish_id IS NOT NULL AND promotion_id IS NULL) OR (dish_id IS NULL AND promotion_id IS NOT NULL)', name=op.f('ck_order_items_one_source')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_order_items_quantity_positive')),
    sa.CheckConstraint('unit_price >= 0', name=op.f('ck_order_items_unit_price_non_negative')),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], name=op.f('fk_order_items_dish_id_dishes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], name=op.f('fk_order_items_promotion_id_promotions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items'))
    )
    op.create_index('idx_order_items_dish_id', 'order_items', ['dish_id'], unique=False)
    op.create_index('idx_order_items_order_id', 'order_items', ['order_id'], unique=False)
    op.create_index('idx_order_items_promotion_id', 'order_items', ['promotion_id'], unique=False)
    op.create_table('order_status_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('status', order_status, nullable=False),
    sa.Column('changed_by', sa.Integer(), nullable=True),
    sa.Column('comment', sa.String(length=250), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_order_status_history_changed_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_status_history_order_id_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_status_history'))
    )
    op.create_index('idx_order_status_history_order_created', 'order_status_history', ['order_id', 'created_at'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('external_id', sa.String(length=100), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', payment_status, server_default='pending', nullable=False),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_payments_amount_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_payments_order_id_orders'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('provider', 'external_id', name='uq_payments_provider_external_id')
    )
    op.create_index('idx_payments_order_id', 'payments', ['order_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema (розширення vector не видаляємо: ним можуть користуватися інші БД/схеми)."""
    op.drop_index('idx_payments_order_id', table_name='payments')
    op.drop_table('payments')
    op.drop_index('idx_order_status_history_order_created', table_name='order_status_history')
    op.drop_table('order_status_history')
    op.drop_index('idx_order_items_promotion_id', table_name='order_items')
    op.drop_index('idx_order_items_order_id', table_name='order_items')
    op.drop_index('idx_order_items_dish_id', table_name='order_items')
    op.drop_table('order_items')
    op.drop_index('idx_orders_location_status', table_name='orders')
    op.drop_index('idx_orders_location_created', table_name='orders')
    op.drop_index('idx_orders_customer_created', table_name='orders')
    op.drop_table('orders')
    op.drop_index('idx_ai_messages_dialog_created', table_name='ai_messages')
    op.drop_table('ai_messages')
    op.drop_index('idx_promotion_items_dish_id', table_name='promotion_items')
    op.drop_table('promotion_items')
    op.drop_index('idx_dish_locations_location_id', table_name='dish_locations')
    op.drop_table('dish_locations')
    op.drop_index('idx_dish_allergens_allergen_id', table_name='dish_allergens')
    op.drop_table('dish_allergens')
    op.drop_table('ai_escalation_triggers')
    op.drop_index('idx_ai_dialogs_location_status', table_name='ai_dialogs')
    op.drop_index('idx_ai_dialogs_customer_created', table_name='ai_dialogs')
    op.drop_index('idx_ai_dialogs_channel_external', table_name='ai_dialogs')
    op.drop_table('ai_dialogs')
    op.drop_table('users')
    op.drop_index('idx_promotion_locations_location_id', table_name='promotion_locations')
    op.drop_table('promotion_locations')
    op.drop_index('idx_dishes_embedding', table_name='dishes', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('idx_dishes_category_id', table_name='dishes')
    op.drop_table('dishes')
    op.drop_table('delivery_zones')
    op.drop_index('uq_customer_addresses_one_default', table_name='customer_addresses', postgresql_where=sa.text('is_default'))
    op.drop_index('idx_customer_addresses_customer_id', table_name='customer_addresses')
    op.drop_table('customer_addresses')
    op.drop_table('ai_settings')
    op.drop_index('idx_promotions_embedding', table_name='promotions', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('promotions')
    op.drop_table('locations')
    op.drop_table('customers')
    op.drop_table('categories')
    op.drop_table('allergens')

    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
