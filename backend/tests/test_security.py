import pytest

from app.core.security import hash_password, needs_rehash, verify_password

PASSWORD = 'Пароль-123'


@pytest.fixture(scope='module')
def stored() -> str:
    return hash_password(PASSWORD)  # хешування повільне навмисно, тому один раз на модуль


def test_correct_password_verifies(stored):
    assert verify_password(PASSWORD, stored)


def test_wrong_password_is_rejected(stored):
    assert not verify_password('Пароль-124', stored)
    assert not verify_password('', stored)


def test_hash_is_salted_and_hides_password(stored):
    assert hash_password(PASSWORD) != stored  # різна сіль, різний хеш
    assert 'Пароль' not in stored


@pytest.mark.parametrize('broken', [
    '',
    'plain-text-password',
    'scrypt$1$2$3',                          # замало частин
    'bcrypt$65536$8$2$AAAA$AAAA',            # чужий алгоритм
    'scrypt$abc$8$2$AAAA$AAAA',              # N не число
    'scrypt$65536$8$2$!!!!$!!!!',            # не base64
    'scrypt$3$8$2$AAAA$AAAA',                # N не степінь двійки
    f'scrypt${10 ** 40}$8$2$AAAA$AAAA',      # абсурдні параметри
])
def test_malformed_hash_gives_false_not_exception(broken):
    assert verify_password(PASSWORD, broken) is False


def test_needs_rehash(stored):
    assert needs_rehash(stored) is False
    assert needs_rehash('scrypt$16384$8$1$AAAA$AAAA') is True  # слабші параметри
    assert needs_rehash('garbage') is True
