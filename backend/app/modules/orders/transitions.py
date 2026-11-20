"""Життєвий цикл замовлення: які зміни статусу можливі і хто їх може робити.

Чисті функції без БД, тому правила легко читати й тестувати окремо від запитів.

Шлях замовлення:

    new ─► confirmed ─► preparing ─► ready ─┬─► completed                 (самовивіз)
      │        │            │         │     └─► out_for_delivery ─► completed   (доставка)
      └────────┴────────────┴─────────┴──────────────┴─► cancelled

- `completed` і `cancelled` кінцеві: з них вийти не можна;
- `out_for_delivery` існує лише в доставки, а самовивіз з `ready` іде просто в `completed`;
- скасувати можна на будь-якому кроці до завершення.

Хто що робить:
- адмін і офіціант: будь-який дозволений перехід (офіціант приймає, віддає, скасовує);
- кухар: лише «взяв у роботу» (confirmed → preparing) і «готово» (preparing → ready).
"""
from app.db.enums import FulfillmentType, OrderStatus, UserRole

S = OrderStatus

FINAL_STATUSES = frozenset({S.completed, S.cancelled})
ACTIVE_STATUSES = frozenset(set(S) - FINAL_STATUSES)

# Кроки, які робить кухар. Усе інше (прийняти, віддати, скасувати) це робота офіціанта чи адміна.
_CHEF_STEPS = frozenset({(S.confirmed, S.preparing), (S.preparing, S.ready)})


def next_statuses(current: S, fulfillment: FulfillmentType) -> list[S]:
    """Усі статуси, у які замовлення можна перевести з поточного (незалежно від ролі), у порядку «вперед, потім скасування»."""
    if current in FINAL_STATUSES:
        return []
    forward = {
        S.new: [S.confirmed],
        S.confirmed: [S.preparing],
        S.preparing: [S.ready],
        S.ready: [S.out_for_delivery] if fulfillment is FulfillmentType.delivery else [S.completed],
        S.out_for_delivery: [S.completed],
    }[current]
    return [*forward, S.cancelled]


def role_may(role: UserRole, current: S, target: S) -> bool:
    """Чи може ця роль зробити саме цей перехід. Дозволеність самого переходу перевіряє `next_statuses`."""
    if role in (UserRole.admin, UserRole.waiter):
        return True
    return (current, target) in _CHEF_STEPS


def allowed_for(role: UserRole, current: S, fulfillment: FulfillmentType, *, paid: bool) -> list[S]:
    """Що саме може натиснути цей працівник просто зараз (для кнопок у інтерфейсі).

    Завершити замовлення можна лише оплаченим: інакше в звітах з'явилися б «виконані» замовлення без грошей.
    Тому, поки оплати немає, `completed` у списку не пропонується (спершу відмітьте оплату).
    """
    return [
        target for target in next_statuses(current, fulfillment)
        if role_may(role, current, target) and (paid or target is not S.completed)
    ]
