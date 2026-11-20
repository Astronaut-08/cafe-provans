"""Фото страв і закладів: завантаження, заміна, видалення, перевірка файлу, віддача з /media."""
import pytest

from app.config import settings
from app.core import media
from app.core.media import MAX_IMAGE_BYTES, detect_image_extension
from app.db.enums import UserRole
from tests.factories import bearer, make_category, make_dish, make_location, make_user

JPEG = b'\xff\xd8\xff\xe0' + b'\x00\x10JFIF' + b'x' * 200
PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 200
WEBP = b'RIFF' + b'\x24\x00\x00\x00' + b'WEBP' + b'VP8 ' + b'x' * 200


def files_of(root, kind: str) -> list[str]:
    folder = root / kind
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def upload(client, url, data=JPEG, name='photo.jpg', content_type='image/jpeg', **kwargs):
    return client.post(url, files={'file': (name, data, content_type)}, **kwargs)


# ---------- визначення типу за вмістом ----------

@pytest.mark.parametrize('data, expected', [
    (JPEG, 'jpg'), (PNG, 'png'), (WEBP, 'webp'),
    (b'GIF89a' + b'x' * 50, None),
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', None),
    (b'<html><script>alert(1)</script></html>', None),
    (b'RIFF\x00\x00\x00\x00WAVEfmt ', None),          # RIFF, але не WebP
    (b'\xff\xd8', None),                              # обірваний заголовок JPEG
    (b'', None),
])
def test_image_type_is_detected_by_content(data, expected):
    assert detect_image_extension(data) == expected


# ---------- фото страви ----------

async def test_upload_dish_image_saves_file_and_returns_its_url(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита')

    response = await upload(client, f'/api/v1/dishes/{dish.id}/image')
    assert response.status_code == 200, response.text
    url = response.json()['image_url']
    assert url.startswith(f'/media/dishes/dish-{dish.id}-') and url.endswith('.jpg')
    assert files_of(media_root, 'dishes') == [url.rsplit('/', 1)[1]]
    assert (media_root / 'dishes' / url.rsplit('/', 1)[1]).read_bytes() == JPEG


async def test_uploaded_image_is_served_from_media_with_safe_headers(client, db_session, login_as):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    url = (await upload(client, f'/api/v1/dishes/{dish.id}/image', PNG, 'a.png', 'image/png')).json()['image_url']

    response = await client.get(url)   # без входу: фото бачать усі
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'max-age' in response.headers['cache-control']


async def test_image_url_reaches_the_public_menu(client, db_session, login_as):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    dish = await make_dish(db_session, await make_category(db_session), 'Маргарита', sell_in=[loc])
    url = (await upload(client, f'/api/v1/dishes/{dish.id}/image')).json()['image_url']
    menu = (await client.get(f'/api/v1/locations/{loc.id}/menu')).json()
    assert menu['categories'][0]['dishes'][0]['image_url'] == url


async def test_new_image_replaces_old_one_on_disk(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    first = (await upload(client, f'/api/v1/dishes/{dish.id}/image', JPEG)).json()['image_url']
    second = (await upload(client, f'/api/v1/dishes/{dish.id}/image', WEBP, 'b.webp', 'image/webp')).json()['image_url']

    assert first != second and second.endswith('.webp')
    assert files_of(media_root, 'dishes') == [second.rsplit('/', 1)[1]]      # старе прибрано
    assert (await client.get(first)).status_code == 404


async def test_delete_image_removes_file_and_url(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    await upload(client, f'/api/v1/dishes/{dish.id}/image')

    response = await client.delete(f'/api/v1/dishes/{dish.id}/image')
    assert response.status_code == 200 and response.json()['image_url'] is None
    assert files_of(media_root, 'dishes') == []
    assert (await client.delete(f'/api/v1/dishes/{dish.id}/image')).status_code == 200   # повторно: нічого не ламається


async def test_deleting_dish_removes_its_image(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    await upload(client, f'/api/v1/dishes/{dish.id}/image')
    assert len(files_of(media_root, 'dishes')) == 1
    assert (await client.delete(f'/api/v1/dishes/{dish.id}')).status_code == 204
    assert files_of(media_root, 'dishes') == []


async def test_type_is_taken_from_content_not_from_name_or_header(client, db_session, login_as):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    # PNG під виглядом .jpg: приймається, і розширення береться з вмісту
    url = (await upload(client, f'/api/v1/dishes/{dish.id}/image', PNG, 'fake.jpg', 'image/jpeg')).json()['image_url']
    assert url.endswith('.png')


async def test_client_filename_never_reaches_the_disk(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    response = await upload(client, f'/api/v1/dishes/{dish.id}/image', JPEG, '../../../evil.jpg')
    assert response.status_code == 200
    assert 'evil' not in response.json()['image_url']
    assert files_of(media_root, 'dishes') == [response.json()['image_url'].rsplit('/', 1)[1]]
    assert not (media_root.parent / 'evil.jpg').exists()


@pytest.mark.parametrize('data, name, ctype', [
    (b'GIF89a' + b'x' * 50, 'a.gif', 'image/gif'),
    (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'a.svg', 'image/svg+xml'),
    (b'just text', 'a.jpg', 'image/jpeg'),                      # назва .jpg не робить текст картинкою
    (b'', 'empty.jpg', 'image/jpeg'),
])
async def test_non_images_are_rejected_and_nothing_is_saved(client, db_session, login_as, media_root, data, name, ctype):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    response = await upload(client, f'/api/v1/dishes/{dish.id}/image', data, name, ctype)
    assert (response.status_code, response.json()['error']['code']) == (422, 'unsupported_image')
    assert files_of(media_root, 'dishes') == []


async def test_rejected_upload_keeps_the_previous_photo(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    url = (await upload(client, f'/api/v1/dishes/{dish.id}/image')).json()['image_url']
    await upload(client, f'/api/v1/dishes/{dish.id}/image', b'not an image', 'x.jpg')
    assert (await client.get(f'/api/v1/dishes/{dish.id}')).json()['image_url'] == url
    assert len(files_of(media_root, 'dishes')) == 1


async def test_image_size_limit(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    exactly = JPEG + b'0' * (MAX_IMAGE_BYTES - len(JPEG))
    assert len(exactly) == MAX_IMAGE_BYTES
    assert (await upload(client, f'/api/v1/dishes/{dish.id}/image', exactly)).status_code == 200

    too_big = exactly + b'0'
    response = await upload(client, f'/api/v1/dishes/{dish.id}/image', too_big)
    assert (response.status_code, response.json()['error']['code']) == (422, 'image_too_large')
    assert len(files_of(media_root, 'dishes')) == 1                         # лишилось попереднє фото


async def test_upload_without_file_is_422(client, db_session, login_as):
    login_as(UserRole.admin)
    dish = await make_dish(db_session, await make_category(db_session))
    assert (await client.post(f'/api/v1/dishes/{dish.id}/image')).status_code == 422
    assert (await client.post(f'/api/v1/dishes/{dish.id}/image', data={'file': 'text'})).status_code == 422


async def test_image_of_unknown_dish_is_404_and_nothing_saved(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    assert (await upload(client, '/api/v1/dishes/9999/image')).status_code == 404
    assert (await client.delete('/api/v1/dishes/9999/image')).status_code == 404
    assert files_of(media_root, 'dishes') == []


async def test_image_endpoints_require_admin(client, db_session, media_root):
    dish = await make_dish(db_session, await make_category(db_session))
    waiter = await make_user(db_session, 'olga', role=UserRole.waiter)
    url = f'/api/v1/dishes/{dish.id}/image'
    assert (await upload(client, url)).status_code == 401
    assert (await upload(client, url, headers=bearer(waiter))).status_code == 403
    assert (await client.delete(url, headers=bearer(waiter))).status_code == 403
    assert files_of(media_root, 'dishes') == []


# ---------- фото закладу ----------

async def test_location_image_upload_replace_and_delete(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    url_base = f'/api/v1/admin/locations/{loc.id}/image'

    first = (await upload(client, url_base)).json()['image_url']
    assert first.startswith(f'/media/locations/location-{loc.id}-') and (await client.get(first)).content == JPEG
    second = (await upload(client, url_base, PNG, 'a.png', 'image/png')).json()['image_url']
    assert files_of(media_root, 'locations') == [second.rsplit('/', 1)[1]]

    # гість бачить фото закладу в публічному API
    assert (await client.get(f'/api/v1/locations/{loc.id}')).json()['image_url'] == second
    assert (await client.get('/api/v1/locations')).json()[0]['image_url'] == second

    assert (await client.delete(url_base)).json()['image_url'] is None
    assert files_of(media_root, 'locations') == []


async def test_location_image_rejects_non_images(client, db_session, login_as, media_root):
    login_as(UserRole.admin)
    loc = await make_location(db_session)
    response = await upload(client, f'/api/v1/admin/locations/{loc.id}/image', b'text', 'a.jpg')
    assert (response.status_code, response.json()['error']['code']) == (422, 'unsupported_image')
    assert (await upload(client, '/api/v1/admin/locations/9999/image')).status_code == 404
    assert files_of(media_root, 'locations') == []


# ---------- внутрішня безпека: видалення файлів ----------

async def test_delete_image_ignores_foreign_and_escaping_urls(media_root):
    outside = media_root.parent / 'must-survive.txt'
    outside.write_text('x')
    inside = media_root / 'dishes' / 'keep.jpg'
    inside.parent.mkdir(parents=True)
    inside.write_bytes(JPEG)
    try:
        await media.delete_image('/media/../must-survive.txt')       # вихід за межі media_dir
        await media.delete_image('https://cdn.example.com/a.jpg')    # зовнішня адреса: диск не чіпаємо
        await media.delete_image(None)
        await media.delete_image('/media/dishes/missing.jpg')         # відсутній файл не помилка
        assert outside.exists() and inside.exists()
        await media.delete_image('/media/dishes/keep.jpg')
        assert not inside.exists()
    finally:
        outside.unlink(missing_ok=True)


async def test_failed_commit_removes_new_file_and_keeps_old(media_root):
    class FakeEntity:
        id = 7
        image_url = '/media/dishes/old.jpg'

    class FailingSession:
        async def commit(self):
            raise RuntimeError('БД недоступна')

        async def rollback(self):
            pass

    old = media_root / 'dishes' / 'old.jpg'
    old.parent.mkdir(parents=True)
    old.write_bytes(JPEG)
    with pytest.raises(RuntimeError):
        await media.replace_image(FailingSession(), FakeEntity(), 'dishes', PNG, 'png')
    assert files_of(media_root, 'dishes') == ['old.jpg']        # нове прибрано, старе на місці


def test_test_suite_never_writes_into_real_media_folder():
    assert 'provans-test-media-' in str(settings.media_dir)
