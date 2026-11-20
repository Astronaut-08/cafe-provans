"""Логування в dev-режимі: виняток має друкуватися коротко, без дампа локальних змінних.

Регресія: за замовчуванням rich друкує локальні змінні кожного кадру стека. Для одного
необробленого винятку під SQLAlchemy це було ~8 МБ тексту, і dev-сервер після першої ж
помилки 500 хвилинами "висів", друкуючи лог.
"""
import io
import sys

from app.core.logging import dev_exception_formatter

SECRET_LOCAL = 'ЦЕ-ЗНАЧЕННЯ-ЛОКАЛЬНОЇ-ЗМІННОЇ'


def _deep(levels: int, payload: dict):
    big_local = {i: SECRET_LOCAL * 20 for i in range(2000)}  # шматок "стану", який раніше потрапляв у лог
    if levels == 0:
        raise RuntimeError('boom-marker')
    _deep(levels - 1, payload | {'level': levels, 'big': big_local})


def _render() -> str:
    try:
        _deep(80, {})
    except RuntimeError:
        buffer = io.StringIO()
        dev_exception_formatter()(buffer, sys.exc_info())
        return buffer.getvalue()
    raise AssertionError('виняток не виник')


def test_dev_traceback_keeps_the_message_and_the_stack():
    text = _render()
    assert 'boom-marker' in text
    assert '_deep' in text  # стек на місці: для налагодження його досить


def test_dev_traceback_does_not_dump_local_variables():
    assert SECRET_LOCAL not in _render()


def test_dev_traceback_output_stays_small_even_for_a_deep_stack():
    # 80 кадрів із великими локальними змінними: з локалями це були б мегабайти
    assert len(_render()) < 100_000
