"""Підсумок оплати замовлення за його платежами.

`orders.payment_status` це підсумок усіх рядків `payments`, і сервіс оновлює його в тій самій транзакції, що й
сам платіж. Саме правило окремо, щоб його можна було перевірити без БД.
"""
from collections.abc import Iterable

from app.db.enums import PaymentStatus


def summarize_payments(statuses: Iterable[PaymentStatus]) -> PaymentStatus:
    """Один статус оплати замовлення за статусами його платежів.

    Пріоритет: усі повернені → refunded; є сплачений → paid; є очікуваний → pending; є невдалий → failed;
    платежів немає взагалі → unpaid. Тобто «гроші є» важливіші за «ще чекаємо», а «чекаємо» важливіше за «не вийшло».
    """
    items = list(statuses)
    if not items:
        return PaymentStatus.unpaid
    if all(s is PaymentStatus.refunded for s in items):
        return PaymentStatus.refunded
    for status in (PaymentStatus.paid, PaymentStatus.pending, PaymentStatus.failed):
        if status in items:
            return status
    return PaymentStatus.unpaid
