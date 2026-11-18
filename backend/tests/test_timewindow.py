"""Щоденне вікно часу та переведення в місцевий час закладу (чисті функції, без БД)."""
from datetime import UTC, datetime, time

import pytest
import structlog
from structlog.testing import capture_logs

from app.core import timewindow
from app.core.timewindow import in_time_window, to_local

T = time


@pytest.mark.parametrize('start, end, current, expected', [
    # звичайне вікно: початок включно, кінець НЕ включно
    (T(10), T(22), T(9, 59), False),
    (T(10), T(22), T(10, 0), True),
    (T(10), T(22), T(21, 59), True),
    (T(10), T(22), T(22, 0), False),
    # через північ
    (T(22), T(2), T(21, 59), False),
    (T(22), T(2), T(22, 0), True),
    (T(22), T(2), T(23, 59), True),
    (T(22), T(2), T(0, 0), True),
    (T(22), T(2), T(1, 59), True),
    (T(22), T(2), T(2, 0), False),
    (T(22), T(2), T(12, 0), False),
    # без обмежень
    (None, None, T(3, 0), True),
    # лише одна межа
    (T(18), None, T(17, 59), False),
    (T(18), None, T(18, 0), True),
    (None, T(12), T(11, 59), True),
    (None, T(12), T(12, 0), False),
    # 00:00-00:00 і будь-які однакові межі означають «цілодобово», а не «ніколи»
    (T(0), T(0), T(15, 0), True),
    (T(9), T(9), T(3, 0), True),
])
def test_in_time_window(start, end, current, expected):
    assert in_time_window(start, end, current) is expected


def test_to_local_follows_daylight_saving_time():
    winter = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    assert to_local(winter, 'Europe/Kyiv').hour == 12   # UTC+2
    assert to_local(summer, 'Europe/Kyiv').hour == 13   # UTC+3


def test_to_local_crosses_midnight():
    moment = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)
    local = to_local(moment, 'Europe/Kyiv')
    assert (local.day, local.hour, local.minute) == (16, 1, 30)


def test_to_local_invalid_timezone_falls_back_to_utc_and_warns(monkeypatch):
    # configure_logging вмикає cache_logger_on_first_use: щойно логер модуля хоч раз спрацював
    # (в іншому тесті), capture_logs його вже не бачить. Свіжий логер робить тест незалежним від порядку.
    monkeypatch.setattr(timewindow, 'log', structlog.get_logger('app.time'))
    moment = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    with capture_logs() as logs:
        local = to_local(moment, 'Mars/Olympus')
    assert local.hour == 10
    assert any(entry['event'] == 'invalid_timezone' for entry in logs)
