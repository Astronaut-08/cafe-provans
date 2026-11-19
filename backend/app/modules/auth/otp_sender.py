"""Доставка одноразового коду для відновлення пароля адміна.

Код надсилає «відправник» (OtpSender). Зараз їх два:
- LogOtpSender: пише код у лог. Лише для розробки (у продакшні налаштування цього не дозволяють);
- SmtpOtpSender: лист на email адміна.

Щоб додати SMS, достатньо написати ще один клас із методом `send` і підключити його в `get_otp_sender`
(і в налаштування OTP_SENDER). Решта коду про канал доставки нічого не знає.
"""
import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import structlog

from app.config import settings

log = structlog.get_logger('app.otp')


@dataclass(frozen=True)
class OtpMessage:
    email: str
    login: str
    full_name: str
    code: str
    ttl_minutes: int


class OtpSender(Protocol):
    async def send(self, message: OtpMessage) -> None: ...


class LogOtpSender:
    async def send(self, message: OtpMessage) -> None:
        log.warning('otp_code_for_development', login=message.login, email=message.email, code=message.code)


class SmtpOtpSender:
    """Лист через SMTP зі стандартної бібліотеки (без додаткових залежностей).
    smtplib блокуючий, тому виконується в окремому потоці."""

    async def send(self, message: OtpMessage) -> None:
        await asyncio.to_thread(self._send_blocking, self._build(message))

    @staticmethod
    def _build(message: OtpMessage) -> EmailMessage:
        mail = EmailMessage()
        mail['Subject'] = 'Provans: код для відновлення пароля'
        mail['From'] = settings.smtp_from
        mail['To'] = message.email
        mail.set_content(
            f'Вітаємо, {message.full_name}!\n\n'
            f'Код для відновлення пароля: {message.code}\n'
            f'Він діє {message.ttl_minutes} хвилин і спрацює лише один раз.\n\n'
            'Якщо ви не просили відновлення пароля, просто проігноруйте цей лист.\n'
        )
        return mail

    @staticmethod
    def _send_blocking(mail: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.smtp_security == 'ssl':
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with server:
            if settings.smtp_security == 'starttls':
                server.starttls(context=context)
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            server.send_message(mail)


def get_otp_sender() -> OtpSender:
    """Залежність FastAPI. У тестах підміняється на «відправника», який просто запам'ятовує код."""
    if settings.otp_sender == 'smtp':
        return SmtpOtpSender()
    return LogOtpSender()


async def deliver_otp(sender: OtpSender, message: OtpMessage) -> None:
    """Викликається у фоні після відповіді клієнту. Збій пошти не повинен ні ламати запит
    (клієнт уже отримав відповідь), ні розкривати, чи існує акаунт, тож лише пишемо його в лог (без коду)."""
    try:
        await sender.send(message)
    except Exception:
        log.exception('otp_delivery_failed', login=message.login)
