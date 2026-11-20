"""Фото страв і закладів: приймання, збереження на диск сервера, видалення, віддача за адресою /media/...

Файли лежать у `settings.media_dir`, у БД зберігається лише адреса виду `/media/dishes/dish-7-3fa9c2d41b0e8a55.jpg`.

Безпека (файл надсилає користувач, тож йому не довіряємо):
- тип визначаємо за ВМІСТОМ файлу (перші байти), а не за назвою чи заголовком, який надіслав клієнт;
  дозволені лише JPEG, PNG, WebP (SVG і HTML відсікаються, бо можуть нести скрипти);
- ім'я файлу генеруємо самі (id + випадковий суфікс), назва від клієнта на диск не потрапляє,
  тож «../../щось» і перезапис чужих файлів неможливі;
- розмір обмежений; відповідь віддається з `X-Content-Type-Options: nosniff`.
"""
import asyncio
import secrets
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles

from app.config import settings
from app.core.exceptions import UnprocessableError

MEDIA_URL = '/media'
# папка -> префікс імені файлу; ключі це і є допустимі значення `kind`
_FILE_PREFIX = {'dishes': 'dish', 'locations': 'location'}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 МБ; при зміні узгодьте client_max_body_size у nginx/conf.d/default.conf


def detect_image_extension(data: bytes) -> str | None:
    """'jpg' | 'png' | 'webp' за першими байтами файлу; None, якщо це не дозволена картинка."""
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    """Читає завантажений файл і перевіряє його. Повертає (вміст, розширення) або кидає 422."""
    data = await file.read(MAX_IMAGE_BYTES + 1)  # +1 байт: так видно, що файл більший за ліміт, не читаючи його весь
    if len(data) > MAX_IMAGE_BYTES:
        raise UnprocessableError(
            f'Файл завеликий: до {MAX_IMAGE_BYTES // (1024 * 1024)} МБ', code='image_too_large',
        )
    extension = detect_image_extension(data)
    if extension is None:
        raise UnprocessableError('Підтримуються лише зображення JPEG, PNG і WebP', code='unsupported_image')
    return data, extension


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # спочатку у тимчасовий файл, потім перейменування: відвідувач ніколи не побачить недописану картинку
    temp = path.with_name(path.name + '.part')
    temp.write_bytes(data)
    temp.replace(path)


async def save_image(kind: str, owner_id: int, data: bytes, extension: str) -> str:
    """Зберігає картинку в media_dir/<kind>/ і повертає адресу для БД. kind: 'dishes' або 'locations'."""
    name = f'{_FILE_PREFIX[kind]}-{owner_id}-{secrets.token_hex(8)}.{extension}'  # dish-7-3fa9c2d41b0e8a55.jpg
    await asyncio.to_thread(_write, settings.media_dir / kind / name, data)
    return f'{MEDIA_URL}/{kind}/{name}'


def _remove(url: str) -> None:
    prefix = MEDIA_URL + '/'
    if not url.startswith(prefix):
        return  # не наш файл (наприклад, посилання на зовнішню картинку): диск не чіпаємо
    root = settings.media_dir.resolve()
    path = (root / url[len(prefix):]).resolve()
    if path.is_relative_to(root):  # страховка від виходу за межі media_dir
        path.unlink(missing_ok=True)


async def delete_image(url: str | None) -> None:
    if url:
        await asyncio.to_thread(_remove, url)


async def replace_image(session: AsyncSession, entity, kind: str, data: bytes, extension: str) -> None:
    """Підміняє фото сутності (страви чи закладу): нове на диск, адреса в БД, потім видаляємо старе.

    Порядок важливий: старе фото видаляємо лише після успішного commit. Якщо commit не вдався,
    прибираємо нове, і в БД та на диску лишається те, що було.
    """
    old_url = entity.image_url
    new_url = await save_image(kind, entity.id, data, extension)
    entity.image_url = new_url
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await delete_image(new_url)
        raise
    await delete_image(old_url)


async def clear_image(session: AsyncSession, entity) -> None:
    old_url = entity.image_url
    entity.image_url = None
    await session.commit()
    await delete_image(old_url)


class MediaFiles(StaticFiles):
    """Віддає /media/... з диска. Імена файлів унікальні (з випадковим суфіксом), тож кешувати можна надовго."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response
