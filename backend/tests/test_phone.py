"""Нормалізація телефону: один номер = один запис, як би його не ввели."""
import pytest

from app.core.phone import normalize_phone


@pytest.mark.parametrize('raw', [
    '0671234567',
    '067 123 45 67',
    '(067) 123-45-67',
    '067.123.45.67',
    '  0671234567  ',
    '380671234567',
    '+380671234567',
    '+38 (067) 123 45 67',
    '80671234567',          # стара «вісімка»: 8 (067) ...
])
def test_ukrainian_forms_become_one_canonical_number(raw):
    assert normalize_phone(raw) == '+380671234567'


def test_international_number_with_plus_is_kept():
    assert normalize_phone('+48 123 456 789') == '+48123456789'


def test_international_length_limits_are_inclusive():
    assert normalize_phone('+12345678') == '+12345678'                    # 8 цифр: найкоротший
    assert normalize_phone('+123456789012345') == '+123456789012345'      # 15 цифр: найдовший


@pytest.mark.parametrize('raw', [
    '',
    '   ',
    'abc',
    '067-abc-45-67',
    '12345',                 # закоротко
    '067123456',             # 9 цифр
    '06712345678',           # 11 цифр, але не «80...»
    '3806712345',            # 10 цифр після 380: закоротко
    '48123456789',           # міжнародний без плюса не приймаємо: неоднозначно
    '481234567890',          # 12 цифр, але не «380...»
    '1234567890',            # 10 цифр, але не з нуля
    '12345678901',           # 11 цифр, але не «80...»
    '+0123456789',           # код країни не починається з нуля
    '+1234567',              # закоротко для E.164
    '+1234567890123456',     # задовго (16 цифр)
    '+38067١٢٣٤٥٦٧',         # арабсько-індійські цифри: лише ASCII
])
def test_garbage_is_rejected(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_normalization_is_idempotent():
    once = normalize_phone('067 123 45 67')
    assert normalize_phone(once) == once
