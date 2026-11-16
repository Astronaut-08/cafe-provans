"""Усі enum-и БД в одному місці.

У моделях використовується `pg_enum(...)` з `create_type=False`: сам тип у Postgres
створює міграція (один раз), а не кожна таблиця окремо.
"""
from enum import Enum

from sqlalchemy import Enum as SQLEnum


class UserRole(str, Enum):
    admin = 'admin'      # головний, доступ до всього
    waiter = 'waiter'    # замовлення (прийом, створення), доступність страв
    chef = 'chef'        # лише зміна статусів замовлень


class OrderSource(str, Enum):
    ai_chat = 'ai_chat'
    waiter = 'waiter'
    website = 'website'


class FulfillmentType(str, Enum):
    delivery = 'delivery'
    pickup = 'pickup'


class OrderStatus(str, Enum):
    new = 'new'
    confirmed = 'confirmed'
    preparing = 'preparing'
    ready = 'ready'
    out_for_delivery = 'out_for_delivery'
    completed = 'completed'
    cancelled = 'cancelled'


class PaymentStatus(str, Enum):
    unpaid = 'unpaid'
    pending = 'pending'
    paid = 'paid'
    failed = 'failed'
    refunded = 'refunded'


class PromotionStatus(str, Enum):
    draft = 'draft'
    active = 'active'
    paused = 'paused'
    archived = 'archived'


class DialogStatus(str, Enum):
    active = 'active'
    waiting_human = 'waiting_human'
    closed = 'closed'


class MessageRole(str, Enum):
    user = 'user'
    assistant = 'assistant'
    system = 'system'
    tool = 'tool'
    staff = 'staff'      # відповідь живої людини з персоналу


def pg_enum(enum_cls: type[Enum], name: str) -> SQLEnum:
    """Postgres ENUM, що зберігає значення (а не імена) і не створює тип сам."""
    return SQLEnum(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda e: [member.value for member in e],
    )
