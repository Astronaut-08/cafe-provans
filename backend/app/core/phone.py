"""Нормалізація телефону гостя.

Гість за телефоном і є «ключем»: `customers.phone` унікальний. Тому один і той самий номер
мусить завжди записуватися однаково, хоч би як його ввели:
    0671234567, 067 123 45 67, (067) 123-45-67, 380671234567, +38 067 123 45 67
усе це стає +380671234567. Інакше один гість розпадеться на кілька «клієнтів».

Підтримуємо українські номери в усіх звичних записах і будь-який міжнародний номер
у форматі E.164, але лише з плюсом (+48 123 456 789 → +48123456789).
"""
import re

_SEPARATORS = re.compile(r'[\s\-().]')


def normalize_phone(raw: str) -> str:
    """Повертає номер у вигляді +<цифри>. Якщо це не схоже на номер, кидає ValueError."""
    text = _SEPARATORS.sub('', raw.strip())
    has_plus = text.startswith('+')
    digits = text[1:] if has_plus else text
    if not digits.isascii() or not digits.isdigit():
        raise ValueError('Телефон має містити лише цифри')

    if has_plus:
        # міжнародний запис; перша цифра коду країни не буває нулем
        if digits.startswith('0') or not 8 <= len(digits) <= 15:
            raise ValueError('Некоректний номер телефону')
        return f'+{digits}'

    # без плюса приймаємо лише українські записи
    if len(digits) == 10 and digits.startswith('0'):        # 0671234567
        return f'+38{digits}'
    if len(digits) == 11 and digits.startswith('80'):       # 80671234567 (стара «вісімка»)
        return f'+3{digits}'
    if len(digits) == 12 and digits.startswith('380'):      # 380671234567
        return f'+{digits}'
    raise ValueError('Некоректний номер телефону')
