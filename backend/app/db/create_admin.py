"""Створення першого адміністратора й аварійне відновлення його пароля. Запуск з папки backend:

    python -m app.db.create_admin --login admin --full-name "Іван Петренко" --email admin@example.com
    python -m app.db.create_admin --login admin --reset-password     # аварійно: адмін втратив доступ і до email

Пароль запитується в терміналі (його не видно, і він не потрапляє в історію команд). Для автоматизації
його можна передати змінною оточення ADMIN_PASSWORD.

Чому окрема команда, а не seed: пароль має хешуватися тим самим кодом, яким потім перевіряється вхід,
а в seed (його запускають на кожному розгортанні) паролі зберігати не можна.

Створений цією командою адмін НЕ мусить міняти пароль при першому вході: він щойно сам його вигадав.
Усі інші працівники створюються вже через API (POST /users), їх створює адміністратор.
"""
import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.enums import UserRole
from app.db.models.user import User
from app.db.session import SessionLocal, engine
from app.modules.auth.service import set_password
from app.modules.users.schemas import Email, FullName, Login, NewPassword


class CreateAdminError(Exception):
    """Зрозуміла людині причина, чому команда не виконана (друкується без стека)."""


def _validate(adapter_type, value, label: str):
    try:
        return TypeAdapter(adapter_type).validate_python(value)
    except ValidationError as exc:
        raise CreateAdminError(f'{label}: {exc.errors()[0]["msg"]}') from None


async def create_admin(session: AsyncSession, *, login: str, password: str, full_name: str, email: str) -> User:
    """Створює адміністратора. Ті самі правила, що й в API: логін у нижньому регістрі, пароль 8-128 символів."""
    user = User(
        login=_validate(Login, login, 'Логін'),
        password_hash=await asyncio.to_thread(hash_password, _validate(NewPassword, password, 'Пароль')),
        full_name=_validate(FullName, full_name, "Ім'я"),
        email=_validate(Email, email, 'Email'),
        role=UserRole.admin,
        must_change_password=False,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise CreateAdminError('Такий логін або email уже використовується') from None
    return user


async def reset_admin_password(session: AsyncSession, *, login: str, password: str) -> User:
    """Аварійно ставить новий пароль адміну, знімає блокування й завершує його входи."""
    user = (await session.execute(select(User).where(User.login == login.strip().lower()))).scalar_one_or_none()
    if user is None or user.role is not UserRole.admin:
        raise CreateAdminError('Адміністратора з таким логіном немає')
    await set_password(session, user, _validate(NewPassword, password, 'Пароль'), datetime.now(UTC), must_change=False)
    await session.commit()
    return user


def _ask_password() -> str:
    password = os.environ.get('ADMIN_PASSWORD')
    if password:
        return password
    password = getpass.getpass('Пароль (від 8 символів): ')
    if getpass.getpass('Повторіть пароль: ') != password:
        raise CreateAdminError('Паролі не збігаються')
    return password


async def main(args: argparse.Namespace) -> None:
    try:
        async with SessionLocal() as session:
            if args.reset_password:
                user = await reset_admin_password(session, login=args.login, password=_ask_password())
                print(f'Пароль адміністратора «{user.login}» змінено, його входи завершено.')
            else:
                if not (args.full_name and args.email):
                    raise CreateAdminError('Для створення потрібні --full-name і --email')
                user = await create_admin(
                    session, login=args.login, password=_ask_password(), full_name=args.full_name, email=args.email,
                )
                print(f'Адміністратора «{user.login}» створено.')
    except CreateAdminError as exc:
        print(f'Помилка: {exc}', file=sys.stderr)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Створення адміністратора або аварійне відновлення його пароля')
    parser.add_argument('--login', required=True)
    parser.add_argument('--full-name')
    parser.add_argument('--email')
    parser.add_argument('--reset-password', action='store_true', help='змінити пароль наявного адміна')
    asyncio.run(main(parser.parse_args()))
