"""Відновлення пароля адміна: «забув пароль» -> код -> новий пароль. Плюс доставка коду (лог / SMTP)."""
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import select

from app.config import settings
from app.db.enums import UserRole
from app.db.models.password_reset_otp import PasswordResetOtp
from app.db.models.refresh_token import RefreshToken
from app.modules.auth import otp_sender
from app.modules.auth.otp_sender import LogOtpSender, OtpMessage, SmtpOtpSender, deliver_otp, get_otp_sender
from app.modules.auth.service import OTP_MAX_ATTEMPTS, OTP_REQUESTS_PER_WINDOW
from tests.factories import PASSWORD, make_user

FORGOT = '/api/v1/auth/forgot-password'
RESET = '/api/v1/auth/reset-password'
LOGIN = '/api/v1/auth/login'
REFRESH = '/api/v1/auth/refresh'
ME = '/api/v1/auth/me'
EMAIL = 'boss@example.com'
NEW = 'Brand-new-1'
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class Outbox:
    """Замість пошти: запам'ятовує, що «надіслали»."""

    def __init__(self) -> None:
        self.sent: list[OtpMessage] = []
        self.fail = False

    async def send(self, message: OtpMessage) -> None:
        if self.fail:
            raise ConnectionError('smtp is down')
        self.sent.append(message)

    @property
    def last_code(self) -> str:
        return self.sent[-1].code


@pytest.fixture
def outbox(application):
    box = Outbox()
    application.dependency_overrides[otp_sender.get_otp_sender] = lambda: box
    return box


@pytest.fixture(autouse=True)
def fixed_time(set_now):
    set_now(T0)


async def admin(db, login='boss', email=EMAIL, **kw):
    return await make_user(db, login, role=UserRole.admin, email=email, **kw)


async def forgot(client, login='boss'):
    return await client.post(FORGOT, json={'login': login})


async def reset(client, code, login='boss', password=NEW):
    return await client.post(RESET, json={'login': login, 'code': code, 'new_password': password})


async def otp_rows(db):
    return (await db.scalars(select(PasswordResetOtp).order_by(PasswordResetOtp.id))).all()


# ---------- запит коду ----------

async def test_forgot_sends_a_six_digit_code_to_the_admin_email(client, db_session, outbox):
    await admin(db_session)
    r = await forgot(client)
    assert r.status_code == 202
    assert len(outbox.sent) == 1
    msg = outbox.sent[0]
    assert msg.email == EMAIL and msg.login == 'boss' and msg.ttl_minutes == 10
    assert len(msg.code) == 6 and msg.code.isdigit()


async def test_code_is_stored_only_as_a_hash_with_expiry(client, db_session, outbox):
    user = await admin(db_session)
    await forgot(client)
    (row,) = await otp_rows(db_session)
    assert row.user_id == user.id and row.attempts == 0 and row.used_at is None
    assert row.created_at == T0 and row.expires_at == T0 + timedelta(minutes=10)
    assert outbox.last_code not in row.code_hash and len(row.code_hash) == 64


async def test_response_is_identical_for_every_kind_of_login(client, db_session, outbox):
    await admin(db_session)
    await make_user(db_session, 'waiter1', role=UserRole.waiter, email='w@example.com')      # не адмін
    await admin(db_session, 'gone', email='g@example.com', active=False)                      # вимкнений
    await admin(db_session, 'nomail', email=None)                                             # без email
    outbox.sent.clear()
    known = await forgot(client, 'boss')
    outbox.sent.clear()
    for login in ('nobody', 'waiter1', 'gone', 'nomail'):
        r = await forgot(client, login)
        assert (r.status_code, r.json()) == (known.status_code, known.json()), login
    assert outbox.sent == []   # і нічого не надіслано
    assert [row.user_id for row in await otp_rows(db_session)] == [(await otp_rows(db_session))[0].user_id]  # лише кодів адміна boss


async def test_forgot_validates_body(client):
    assert (await client.post(FORGOT, json={})).status_code == 422
    assert (await client.post(FORGOT, json={'login': 'a', 'extra': 1})).status_code == 422


async def test_forgot_is_rate_limited_per_hour(client, db_session, outbox, set_now):
    await admin(db_session)
    for _ in range(OTP_REQUESTS_PER_WINDOW):
        assert (await forgot(client)).status_code == 202
    assert len(outbox.sent) == OTP_REQUESTS_PER_WINDOW
    r = await forgot(client)   # відповідь та сама, але листа немає
    assert r.status_code == 202 and len(outbox.sent) == OTP_REQUESTS_PER_WINDOW
    set_now(T0 + timedelta(hours=1) - timedelta(seconds=1))
    await forgot(client)
    assert len(outbox.sent) == OTP_REQUESTS_PER_WINDOW
    set_now(T0 + timedelta(hours=1))   # рівно година: коди з T0 уже не враховуються
    await forgot(client)
    assert len(outbox.sent) == OTP_REQUESTS_PER_WINDOW + 1
    # старі коди (старші за вікно) прибрано
    assert all(row.created_at > T0 for row in await otp_rows(db_session))


async def test_rate_limit_is_per_user(client, db_session, outbox):
    await admin(db_session, 'boss', 'a@example.com')
    await admin(db_session, 'boss2', 'b@example.com')
    for _ in range(OTP_REQUESTS_PER_WINDOW + 1):
        await forgot(client, 'boss')
    before = len(outbox.sent)
    await forgot(client, 'boss2')
    assert len(outbox.sent) == before + 1 and outbox.sent[-1].email == 'b@example.com'


async def test_mail_failure_does_not_break_the_request(client, db_session, outbox):
    await admin(db_session)
    outbox.fail = True
    r = await forgot(client)
    assert r.status_code == 202 and r.json() == (await forgot(client, 'nobody')).json()


async def test_failed_delivery_is_logged_without_the_code(monkeypatch):
    # structlog кешує логер при першому використанні, тож беремо свіжий, який бачить capture_logs
    monkeypatch.setattr(otp_sender, 'log', structlog.get_logger('app.otp'))
    box = Outbox()
    box.fail = True
    message = OtpMessage(email=EMAIL, login='boss', full_name='Boss', code='123456', ttl_minutes=10)
    with structlog.testing.capture_logs() as logs:
        await deliver_otp(box, message)
    assert [entry['event'] for entry in logs] == ['otp_delivery_failed']
    assert '123456' not in str(logs).replace("'login': 'boss'", '')


# ---------- новий пароль за кодом ----------

async def test_reset_sets_the_new_password(client, db_session, outbox):
    user = await admin(db_session)
    await forgot(client)
    r = await reset(client, outbox.last_code)
    assert r.status_code == 204 and r.content == b''
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': NEW})).status_code == 200
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': PASSWORD})).status_code == 401
    await db_session.refresh(user)
    assert user.must_change_password is False


async def test_code_works_only_once(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    code = outbox.last_code
    assert (await reset(client, code)).status_code == 204
    r = await reset(client, code, password='Another-pass-2')
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_otp'
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': NEW})).status_code == 200


async def test_wrong_code_is_rejected_and_attempts_are_counted(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    wrong = '000000' if outbox.last_code != '000000' else '111111'
    r = await reset(client, wrong)
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_otp'
    assert (await otp_rows(db_session))[0].attempts == 1   # зафіксовано, хоч відповідь помилкова
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': PASSWORD})).status_code == 200   # пароль не змінено


async def test_attempts_run_out_even_for_the_correct_code(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    code = outbox.last_code
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(OTP_MAX_ATTEMPTS):
        assert (await reset(client, wrong)).status_code == 422
    r = await reset(client, code)
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_otp'
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': PASSWORD})).status_code == 200


async def test_last_allowed_attempt_still_works(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    code = outbox.last_code
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(OTP_MAX_ATTEMPTS - 1):
        await reset(client, wrong)
    assert (await reset(client, code)).status_code == 204


async def test_code_expires_after_ten_minutes(client, db_session, outbox, set_now):
    await admin(db_session)
    await forgot(client)
    code = outbox.last_code
    set_now(T0 + timedelta(minutes=10))
    r = await reset(client, code)
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_otp'


async def test_code_still_works_a_second_before_it_expires(client, db_session, outbox, set_now):
    await admin(db_session)
    await forgot(client)
    set_now(T0 + timedelta(minutes=10) - timedelta(seconds=1))
    assert (await reset(client, outbox.last_code)).status_code == 204


async def test_only_the_newest_code_counts(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    first = outbox.last_code
    await forgot(client)
    second = outbox.last_code
    if first == second:   # шанс 1 на мільйон, але тест не повинен через це падати
        pytest.skip('збіглися випадкові коди')
    assert (await reset(client, first)).status_code == 422
    assert (await reset(client, second)).status_code == 204


async def test_successful_reset_cancels_all_other_codes(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    await forgot(client)
    await reset(client, outbox.last_code)
    assert all(row.used_at == T0 for row in await otp_rows(db_session))


async def test_reset_ends_all_sessions_and_removes_the_lock(client, db_session, outbox, set_now):
    user = await admin(db_session)
    session_before = (await client.post(LOGIN, json={'login': 'boss', 'password': PASSWORD})).json()
    # адміну підбирали пароль, і акаунт заблоковано
    user.locked_until = T0 + timedelta(minutes=10)
    user.failed_login_attempts = 3
    await db_session.commit()
    await forgot(client)
    assert (await reset(client, outbox.last_code)).status_code == 204

    await db_session.refresh(user)
    assert user.locked_until is None and user.failed_login_attempts == 0 and user.token_version == 1
    # старі токени мертві
    old = {'Authorization': f'Bearer {session_before["access_token"]}'}
    assert (await client.get(ME, headers=old)).status_code == 401
    assert (await client.post(REFRESH, json={'refresh_token': session_before['refresh_token']})).status_code == 401
    assert all(t.revoked_at is not None for t in (await db_session.scalars(select(RefreshToken))).all())
    # а новий пароль пускає одразу, без очікування кінця блокування
    assert (await client.post(LOGIN, json={'login': 'boss', 'password': NEW})).status_code == 200


async def test_forgot_works_for_a_locked_account(client, db_session, outbox):
    await admin(db_session, locked_until=T0 + timedelta(minutes=10))
    await forgot(client)
    assert len(outbox.sent) == 1


@pytest.mark.parametrize('kind', ['unknown', 'waiter', 'disabled', 'no_code_requested'])
async def test_reset_failures_are_indistinguishable(client, db_session, outbox, kind):
    await admin(db_session)
    await forgot(client)
    wrong = '000000' if outbox.last_code != '000000' else '111111'
    login = 'boss'
    if kind == 'unknown':
        login = 'nobody'
    elif kind == 'waiter':
        await make_user(db_session, 'waiter1', role=UserRole.waiter, email='w@example.com')
        login = 'waiter1'
    elif kind == 'disabled':
        await admin(db_session, 'gone', 'g@example.com', active=False)
        await forgot(client, 'gone')
        login = 'gone'
    elif kind == 'no_code_requested':
        await admin(db_session, 'other', 'o@example.com')
        login = 'other'
    wrong_for_boss = await reset(client, wrong, login='boss')
    r = await reset(client, outbox.last_code if kind == 'waiter' else wrong, login=login)
    assert r.status_code == wrong_for_boss.status_code == 422
    assert r.json()['error']['code'] == wrong_for_boss.json()['error']['code'] == 'invalid_otp'
    assert r.json()['error']['message'] == wrong_for_boss.json()['error']['message']


async def test_code_of_one_admin_does_not_work_for_another(client, db_session, outbox):
    await admin(db_session, 'boss', 'a@example.com')
    await admin(db_session, 'boss2', 'b@example.com')
    await forgot(client, 'boss')
    r = await reset(client, outbox.last_code, login='boss2')
    assert r.status_code == 422


@pytest.mark.parametrize('code', ['12345', '1234567', 'abcdef', '12 456', '', '١٢٣٤٥٦'])
async def test_code_format_is_validated(client, db_session, outbox, code):
    r = await reset(client, code)
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'


async def test_new_password_policy_applies_to_reset(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    r = await reset(client, outbox.last_code, password='q7!zK')
    assert r.status_code == 422 and r.json()['error']['code'] == 'validation_error'
    # слабкий пароль не «спалив» код
    assert (await reset(client, outbox.last_code)).status_code == 204


async def test_code_with_spaces_around_is_accepted(client, db_session, outbox):
    await admin(db_session)
    await forgot(client)
    assert (await reset(client, f' {outbox.last_code} ')).status_code == 204


# ---------- відправники ----------

def test_get_otp_sender_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, 'otp_sender', 'log')
    assert isinstance(get_otp_sender(), LogOtpSender)
    monkeypatch.setattr(settings, 'otp_sender', 'smtp')
    assert isinstance(get_otp_sender(), SmtpOtpSender)


async def test_log_sender_writes_the_code_to_the_log(monkeypatch):
    monkeypatch.setattr(otp_sender, 'log', structlog.get_logger('app.otp'))
    with structlog.testing.capture_logs() as logs:
        await LogOtpSender().send(OtpMessage(email=EMAIL, login='boss', full_name='Boss', code='654321', ttl_minutes=10))
    assert logs[0]['code'] == '654321' and logs[0]['login'] == 'boss'


class FakeSmtp:
    instances: list['FakeSmtp'] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[tuple] = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(('quit',))

    def starttls(self, context=None):
        self.calls.append(('starttls', context is not None))

    def login(self, user, password):
        self.calls.append(('login', user, password))

    def send_message(self, mail):
        self.calls.append(('send', mail))


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(otp_sender.smtplib, 'SMTP', FakeSmtp)
    monkeypatch.setattr(otp_sender.smtplib, 'SMTP_SSL', type('FakeSmtpSsl', (FakeSmtp,), {}))
    for name, value in dict(
        smtp_host='mail.example.com', smtp_port=587, smtp_user='robot', smtp_password=settings.jwt_secret.__class__('pw-1234'),
        smtp_from='Provans <no-reply@example.com>', smtp_security='starttls',
    ).items():
        monkeypatch.setattr(settings, name, value)
    return FakeSmtp


MESSAGE = OtpMessage(email=EMAIL, login='boss', full_name='Іван', code='042042', ttl_minutes=10)


async def test_smtp_sends_a_mail_with_the_code_over_starttls(fake_smtp):
    await SmtpOtpSender().send(MESSAGE)
    (server,) = fake_smtp.instances
    assert (server.host, server.port) == ('mail.example.com', 587)
    kinds = [call[0] for call in server.calls]
    assert kinds == ['starttls', 'login', 'send', 'quit']      # шифрування ДО передачі пароля
    assert ('login', 'robot', 'pw-1234') in server.calls
    mail = next(call[1] for call in server.calls if call[0] == 'send')
    assert mail['To'] == EMAIL and mail['From'] == 'Provans <no-reply@example.com>'
    body = mail.get_content()
    assert '042042' in body and '10 хвилин' in body and 'Іван' in body


async def test_smtp_ssl_mode_does_not_use_starttls(fake_smtp, monkeypatch):
    monkeypatch.setattr(settings, 'smtp_security', 'ssl')
    monkeypatch.setattr(settings, 'smtp_port', 465)
    await SmtpOtpSender().send(MESSAGE)
    (server,) = fake_smtp.instances
    assert type(server).__name__ == 'FakeSmtpSsl' and server.port == 465
    assert 'starttls' not in [call[0] for call in server.calls]


async def test_smtp_without_credentials_skips_login(fake_smtp, monkeypatch):
    monkeypatch.setattr(settings, 'smtp_user', None)
    monkeypatch.setattr(settings, 'smtp_password', None)
    monkeypatch.setattr(settings, 'smtp_security', 'none')
    await SmtpOtpSender().send(MESSAGE)
    assert [call[0] for call in fake_smtp.instances[0].calls] == ['send', 'quit']


async def test_smtp_rejects_an_address_with_header_injection(fake_smtp):
    bad = OtpMessage(email='a@example.com\r\nBcc: evil@example.com', login='x', full_name='X', code='1', ttl_minutes=10)
    with pytest.raises(ValueError):
        await SmtpOtpSender().send(bad)
    assert fake_smtp.instances == []
