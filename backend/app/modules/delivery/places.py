"""Нормалізація назв міст і вулиць для зіставлення адреси гостя зі списком, який веде адміністратор.

Мета: «вул. Шевченка, 5», «Шевченка вулиця» і «ШЕВЧЕНКА» мають знайти один і той самий запис, а
«вул. Шевченка» й «пров. Шевченка» (у малих містах такі існують поруч) не повинні змішуватись.

Чиста логіка без БД. Назви в БД лежать так, як їх ввів адміністратор; нормалізується обидва боки
під час порівняння.
"""
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

# Апостроф у різних написаннях (' ’ ʼ ` ´), а ще й часто його просто не ставлять: усі варіанти мають збігатися
_APOSTROPHES = re.compile("['’ʼʹ‘`´′]")
_DASHES = re.compile('[‐‑‒–—―−]')
# розділювачі токенів; дефіс і похила риска лишаються всередині слова («Івано-Франківська», «12/3»)
_SEPARATORS = re.compile(r'[\s.,;:()«»"]+')

# Тип вулиці -> канонічний. Тип входить у ключ вулиці, бо «вул. Шевченка» і «пров. Шевченка» різні.
_STREET_KINDS = {
    'вул': 'вул', 'вулиця': 'вул', 'вулиці': 'вул',
    'пров': 'пров', 'провулок': 'пров',
    'просп': 'просп', 'проспект': 'просп', 'пр-т': 'просп', 'пр-кт': 'просп',
    'бул': 'бул', 'бульвар': 'бул',
    'пл': 'пл', 'площа': 'пл',
    'узвіз': 'узвіз', 'тупик': 'тупик', 'наб': 'наб', 'набережна': 'наб',
    'шосе': 'шосе', 'алея': 'алея', 'майдан': 'майдан', 'проїзд': 'проїзд',
}
# Тип населеного пункту нічого не відрізняє («м. Болехів» і «Болехів» одне й те саме), тож просто відкидається
_CITY_KINDS = {'м', 'місто', 'с', 'село', 'смт', 'селище', 'с-ще'}
# У кінці відкидаємо лише скорочення: повні слова там бувають частиною назви («Нове Місто», «Нове Село»)
_CITY_KINDS_AT_END = {'м', 'с', 'смт'}
_HOUSE_MARKERS = {'буд', 'будинок', '№'}
_HOUSE_NUMBER = re.compile(r'^\d+[а-яіїєґa-z]?(/\d+[а-яіїєґa-z]?)?$')


def _tokens(raw: str) -> list[str]:
    text = _APOSTROPHES.sub('', raw.casefold())
    text = _DASHES.sub('-', text).replace('№', ' № ')
    tokens = [t.strip('-') for t in _SEPARATORS.split(text)]
    return [t for t in tokens if t]


def normalize_city(raw: str | None) -> str:
    """'м. Болехів', 'Болехів', ' БОЛЕХІВ ' -> 'болехів'. Порожній рядок, якщо назви немає."""
    tokens = _tokens(raw or '')
    # саме скорочення («м.», «с.», «смт») без назви це не місто; повне слово («Село») лишаємо як назву
    if len(tokens) == 1 and tokens[0] in _CITY_KINDS_AT_END | {'с-ще'}:
        return ''
    # тип відкидаємо лише коли є ще слова: село з назвою «Село» не повинно зникнути
    if len(tokens) > 1 and tokens[0] in _CITY_KINDS:
        tokens = tokens[1:]
    elif len(tokens) > 1 and tokens[-1] in _CITY_KINDS_AT_END:
        tokens = tokens[:-1]
    return ' '.join(tokens)


@dataclass(frozen=True)
class Street:
    name: str           # без типу й номера будинку: 'шевченка'
    kind: str | None    # 'вул', 'пров', ...; None, якщо тип не вказано


def parse_street(raw: str | None) -> Street | None:
    """'вул. Шевченка, 5' -> Street('шевченка', 'вул'). None, якщо вулиці немає (порожній ввід)."""
    tokens = _tokens(raw or '')

    # номер будинку в кінці («Шевченка 5а», «Шевченка буд. 12/3», «Шевченка №5») не частина назви;
    # але «8 Березня» чи «40-річчя Перемоги» чіпати не можна: там число не в кінці або не «голе»
    while len(tokens) > 1 and _HOUSE_NUMBER.match(tokens[-1]):
        tokens.pop()
        if len(tokens) > 1 and tokens[-1] in _HOUSE_MARKERS:
            tokens.pop()

    # лишився самий номер чи позначка («5», «№ 5», «буд. 5»): це не вулиця
    if all(_HOUSE_NUMBER.match(t) or t in _HOUSE_MARKERS for t in tokens):
        return None

    kind = None
    if len(tokens) > 1 and tokens[0] in _STREET_KINDS:
        kind = _STREET_KINDS[tokens.pop(0)]
    elif len(tokens) > 1 and tokens[-1] in _STREET_KINDS:
        kind = _STREET_KINDS[tokens.pop()]

    name = ' '.join(tokens)
    return Street(name, kind) if name else None


T = TypeVar('T')


def find_street(requested: Street, entries: Sequence[tuple[Street, T]]) -> list[T]:
    """Які записи списку відповідають вулиці з запиту (значення T віддаються як є: зона, id тощо).

    - назва має збігтись;
    - гість вказав тип: підходять записи цього ж типу, а якщо таких немає, то записи без типу
      (адміністратор написав просто «Шевченка»); запис іншого типу («пров.») не підходить;
    - гість тип не вказав: підходять усі записи з такою назвою; чи це неоднозначність, вирішує викликач.
    """
    same_name = [(street, value) for street, value in entries if street.name == requested.name]
    if requested.kind is None:
        return [value for _, value in same_name]
    exact = [value for street, value in same_name if street.kind == requested.kind]
    if exact:
        return exact
    return [value for street, value in same_name if street.kind is None]
