"""Правила замовлень без БД: переходи статусів за ролями й підсумок оплати."""
import itertools

import pytest

from app.db.enums import FulfillmentType, OrderStatus, PaymentStatus, UserRole
from app.modules.orders.transitions import (
    ACTIVE_STATUSES, FINAL_STATUSES, allowed_for, next_statuses, role_may,
)
from app.modules.payments.rules import summarize_payments

S = OrderStatus
DELIVERY = FulfillmentType.delivery
PICKUP = FulfillmentType.pickup


# ---------- шлях замовлення ----------

def test_pickup_path():
    path = [S.new]
    while True:
        forward = [s for s in next_statuses(path[-1], PICKUP) if s is not S.cancelled]
        if not forward:
            break
        path.append(forward[0])
    assert path == [S.new, S.confirmed, S.preparing, S.ready, S.completed]


def test_delivery_path_goes_through_out_for_delivery():
    path = [S.new]
    while True:
        forward = [s for s in next_statuses(path[-1], DELIVERY) if s is not S.cancelled]
        if not forward:
            break
        path.append(forward[0])
    assert path == [S.new, S.confirmed, S.preparing, S.ready, S.out_for_delivery, S.completed]


def test_out_for_delivery_is_delivery_only_and_pickup_skips_it():
    assert S.out_for_delivery not in next_statuses(S.ready, PICKUP)
    assert S.completed not in next_statuses(S.ready, DELIVERY)


@pytest.mark.parametrize('fulfillment', [PICKUP, DELIVERY])
@pytest.mark.parametrize('final', [S.completed, S.cancelled])
def test_final_statuses_have_no_way_out(final, fulfillment):
    assert next_statuses(final, fulfillment) == []


@pytest.mark.parametrize('fulfillment', [PICKUP, DELIVERY])
@pytest.mark.parametrize('current', sorted(ACTIVE_STATUSES, key=lambda s: s.value))
def test_every_active_status_can_be_cancelled(current, fulfillment):
    assert S.cancelled in next_statuses(current, fulfillment)


def test_status_groups_cover_every_status_exactly_once():
    assert FINAL_STATUSES | ACTIVE_STATUSES == set(S)
    assert not FINAL_STATUSES & ACTIVE_STATUSES


def test_cannot_skip_or_go_back():
    for fulfillment, current, target in itertools.product([PICKUP, DELIVERY], S, S):
        if target is S.cancelled:
            continue
        allowed = next_statuses(current, fulfillment)
        if target in allowed:
            # назад і «на місці» ходити не можна, лише на один крок уперед
            order = [S.new, S.confirmed, S.preparing, S.ready, S.out_for_delivery, S.completed]
            assert order.index(target) == order.index(current) + 1 or (
                current is S.ready and target is S.completed
            )


# ---------- ролі ----------

@pytest.mark.parametrize('role', [UserRole.admin, UserRole.waiter])
def test_admin_and_waiter_may_do_any_allowed_step(role):
    for fulfillment, current in itertools.product([PICKUP, DELIVERY], S):
        for target in next_statuses(current, fulfillment):
            assert role_may(role, current, target)


def test_chef_may_only_start_cooking_and_finish_cooking():
    chef_steps = {
        (current, target)
        for current, target in itertools.product(S, S)
        if role_may(UserRole.chef, current, target)
    }
    assert chef_steps == {(S.confirmed, S.preparing), (S.preparing, S.ready)}


def test_chef_cannot_cancel_or_accept_or_hand_over():
    assert not role_may(UserRole.chef, S.new, S.confirmed)
    assert not role_may(UserRole.chef, S.preparing, S.cancelled)
    assert not role_may(UserRole.chef, S.ready, S.completed)
    assert not role_may(UserRole.chef, S.ready, S.out_for_delivery)


def test_allowed_for_chef_in_kitchen_statuses():
    assert allowed_for(UserRole.chef, S.confirmed, PICKUP, paid=False) == [S.preparing]
    assert allowed_for(UserRole.chef, S.preparing, DELIVERY, paid=True) == [S.ready]
    assert allowed_for(UserRole.chef, S.new, PICKUP, paid=False) == []
    assert allowed_for(UserRole.chef, S.ready, PICKUP, paid=True) == []


def test_allowed_for_waiter_hides_completed_until_paid():
    assert allowed_for(UserRole.waiter, S.ready, PICKUP, paid=False) == [S.cancelled]
    assert allowed_for(UserRole.waiter, S.ready, PICKUP, paid=True) == [S.completed, S.cancelled]
    assert allowed_for(UserRole.waiter, S.out_for_delivery, DELIVERY, paid=False) == [S.cancelled]
    assert allowed_for(UserRole.waiter, S.out_for_delivery, DELIVERY, paid=True) == [S.completed, S.cancelled]


def test_allowed_for_other_steps_does_not_depend_on_payment():
    for paid in (True, False):
        assert allowed_for(UserRole.waiter, S.new, PICKUP, paid=paid) == [S.confirmed, S.cancelled]
        assert allowed_for(UserRole.waiter, S.ready, DELIVERY, paid=paid) == [S.out_for_delivery, S.cancelled]


# ---------- підсумок оплати ----------

P = PaymentStatus


@pytest.mark.parametrize('statuses, expected', [
    ([], P.unpaid),
    ([P.pending], P.pending),
    ([P.paid], P.paid),
    ([P.failed], P.failed),
    ([P.refunded], P.refunded),
    ([P.refunded, P.refunded], P.refunded),
    ([P.paid, P.pending], P.paid),         # гроші є: важливіше за «ще чекаємо»
    ([P.pending, P.failed], P.pending),    # «чекаємо» важливіше за «не вийшло»
    ([P.failed, P.paid], P.paid),
    ([P.refunded, P.paid], P.paid),        # частково повернено: решта все ще сплачена
    ([P.refunded, P.pending], P.pending),
    ([P.refunded, P.failed], P.failed),
])
def test_summarize_payments(statuses, expected):
    assert summarize_payments(statuses) is expected


def test_summarize_accepts_a_generator():
    assert summarize_payments(s for s in [P.paid]) is P.paid
