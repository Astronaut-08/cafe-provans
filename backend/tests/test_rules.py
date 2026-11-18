"""Бізнес-правила без БД: ціна страви в закладі, доступність, «чи діє акція зараз»."""
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.modules.menu.pricing import effective_price, is_dish_available
from app.modules.promotions.rules import promotion_is_current

D = Decimal


# ---------- ціна ----------

def test_price_override_replaces_base_price():
    assert effective_price(D('200.00'), D('180.00')) == D('180.00')


def test_no_override_uses_base_price():
    assert effective_price(D('200.00'), None) == D('200.00')


def test_zero_override_is_a_real_price_not_a_missing_one():
    # «if override» помилково дало б базову ціну; безкоштовна позиція в закладі це валідний випадок
    assert effective_price(D('200.00'), D('0.00')) == D('0.00')


@pytest.mark.parametrize('dish, location, expected', [
    (True, True, True),
    (False, True, False),    # вимкнено глобально
    (True, False, False),    # вимкнено в цьому закладі
    (False, False, False),
    (True, None, False),     # страви немає в закладі взагалі (outer join дав NULL)
])
def test_dish_availability(dish, location, expected):
    assert is_dish_available(dish, location) is expected


# ---------- акція ----------

def now(y=2026, mo=1, d=15, h=12, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi)


def current(*, start_date=None, end_date=None, start_time=None, end_time=None, local_now=None) -> bool:
    return promotion_is_current(
        start_date=start_date, end_date=end_date, start_time=start_time, end_time=end_time,
        local_now=local_now or now(),
    )


def test_promotion_without_limits_is_always_current():
    assert current() is True


def test_date_range_is_inclusive_on_both_ends():
    assert current(start_date=date(2026, 1, 15), end_date=date(2026, 1, 15)) is True
    assert current(start_date=date(2026, 1, 16)) is False
    assert current(end_date=date(2026, 1, 14)) is False


def test_time_window():
    assert current(start_time=time(11), end_time=time(15)) is True
    assert current(start_time=time(12, 1), end_time=time(15)) is False
    assert current(start_time=time(10), end_time=time(12)) is False   # кінець не включно


def test_overnight_promotion_morning_belongs_to_previous_day():
    # акція до 31 грудня, 22:00-02:00: 1 січня о 01:00 вона ще діє (вечір 31-го)
    kwargs = dict(end_date=date(2026, 12, 31), start_time=time(22), end_time=time(2))
    assert current(**kwargs, local_now=now(2027, 1, 1, 1, 0)) is True
    # а о 23:00 1 січня вже ні: це вечір 1-го, поза end_date
    assert current(**kwargs, local_now=now(2027, 1, 1, 23, 0)) is False


def test_overnight_promotion_start_date_checked_against_window_start_day():
    # акція з 1 січня 22:00-02:00: уранці 1 січня о 01:00 вона ще НЕ діє (вікно почнеться ввечері)
    kwargs = dict(start_date=date(2027, 1, 1), start_time=time(22), end_time=time(2))
    assert current(**kwargs, local_now=now(2027, 1, 1, 1, 0)) is False
    assert current(**kwargs, local_now=now(2027, 1, 1, 22, 30)) is True
    assert current(**kwargs, local_now=now(2027, 1, 2, 1, 0)) is True


def test_overnight_window_outside_hours_is_not_current():
    assert current(start_time=time(22), end_time=time(2), local_now=now(h=12)) is False
