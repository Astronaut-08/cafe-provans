"""Нормалізація міст і вулиць та зіставлення вулиці зі списком (чисті функції, без БД)."""
import pytest

from app.modules.delivery.places import Street, find_street, normalize_city, parse_street


# ---------- місто ----------

@pytest.mark.parametrize('raw', [
    'Болехів', 'болехів', 'БОЛЕХІВ', '  Болехів  ', 'м. Болехів', 'м.Болехів', 'місто Болехів', 'Болехів, м.',
])
def test_city_variants_of_bolekhiv_are_equal(raw):
    assert normalize_city(raw) == 'болехів'


@pytest.mark.parametrize('raw', [
    "Велика Тур'я", 'Велика Турʼя', 'Велика Тур’я', 'Велика Тур`я', 'Велика Туря', 'с. Велика Тур\'я', 'село Велика Тур’я',
])
def test_city_apostrophe_in_any_form_or_missing_is_equal(raw):
    assert normalize_city(raw) == 'велика туря'


@pytest.mark.parametrize('raw, expected', [
    ('смт Журавно', 'журавно'),
    ('Івано-Франківськ', 'івано-франківськ'),
    ('Івано–Франківськ', 'івано-франківськ'),      # довге тире з Word
    ('Нове   Місто', 'нове місто'),                # «Місто» тут частина назви, не тип
    ('Нове Село', 'нове село'),
    ('Старе Село', 'старе село'),
    ('с. Нове Село', 'нове село'),                 # а на початку це тип, його відкидаємо
    ('Нове Село, с.', 'нове село'),
    ('Село', 'село'),                              # єдине повне слово лишається назвою, а не «типом»
    ('м.', ''), ('с', ''), ('смт.', ''),           # саме скорочення без назви це не місто
    ('', ''), ('   ', ''), (None, ''),
])
def test_city_other_cases(raw, expected):
    assert normalize_city(raw) == expected


# ---------- вулиця ----------

@pytest.mark.parametrize('raw', [
    'вул. Шевченка', 'вулиця Шевченка', 'Вул Шевченка', 'ВУЛИЦЯ ШЕВЧЕНКА', 'Шевченка вулиця', 'Шевченка вул.',
    'вул. Шевченка, 5', 'вул. Шевченка 5а', 'вул. Шевченка буд. 12/3', 'вул. Шевченка №5', 'вул.  Шевченка',
])
def test_street_variants_collapse_to_the_same_street(raw):
    assert parse_street(raw) == Street('шевченка', 'вул')


@pytest.mark.parametrize('raw, expected', [
    ('Шевченка', Street('шевченка', None)),
    ('пров. Шевченка', Street('шевченка', 'пров')),
    ('провулок Шевченка', Street('шевченка', 'пров')),
    ('просп. Свободи', Street('свободи', 'просп')),
    ('площа Ринок', Street('ринок', 'пл')),
    ('вул. Лесі Українки 10', Street('лесі українки', 'вул')),
    ('вул. Івана-Франка', Street('івана-франка', 'вул')),
    ("вул. Пʼятницька", Street('пятницька', 'вул')),
    # число всередині назви не відкидається, відкидається лише номер будинку в кінці
    ('вул. 8 Березня', Street('8 березня', 'вул')),
    ('вул. 8 Березня 5', Street('8 березня', 'вул')),
    ('вул. 40-річчя Перемоги 3', Street('40-річчя перемоги', 'вул')),
    ('Тупик', Street('тупик', None)),              # єдине слово лишається назвою
])
def test_street_parsing(raw, expected):
    assert parse_street(raw) == expected


@pytest.mark.parametrize('raw', ['', '   ', None, '5', '№ 5', 'буд. 5', '12/3'])
def test_no_street_gives_none(raw):
    # порожній ввід або самий номер будинку: вулиці немає
    assert parse_street(raw) is None


def test_street_and_alley_with_same_name_are_different_keys():
    assert parse_street('вул. Шевченка') != parse_street('пров. Шевченка')


# ---------- зіставлення зі списком ----------

VUL = Street('шевченка', 'вул')
PROV = Street('шевченка', 'пров')
BARE = Street('шевченка', None)
OTHER = Street('франка', 'вул')


def test_find_exact_kind_wins_over_generic():
    entries = [(BARE, 'generic'), (VUL, 'vul'), (PROV, 'prov')]
    assert find_street(VUL, entries) == ['vul']
    assert find_street(PROV, entries) == ['prov']


def test_find_falls_back_to_entry_without_kind():
    # адміністратор написав просто «Шевченка», гість «вул. Шевченка»
    assert find_street(VUL, [(BARE, 'generic'), (OTHER, 'x')]) == ['generic']


def test_find_does_not_match_other_kind():
    assert find_street(VUL, [(PROV, 'prov')]) == []


def test_find_without_kind_returns_every_street_with_that_name():
    # гість написав «Шевченка» без типу; чи це неоднозначність, вирішує викликач за зонами
    assert find_street(BARE, [(VUL, 'vul'), (PROV, 'prov'), (OTHER, 'x')]) == ['vul', 'prov']


def test_find_different_name_never_matches():
    assert find_street(VUL, [(OTHER, 'x')]) == []
    assert find_street(VUL, []) == []
