#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отправка email (SMTP)
AutoDialer Ultimate v3.0.0

Единственная точка отправки писем в проекте. Раньше welcome-письмо и
письмо восстановления пароля (app/services/user.py) не отправлялись
вообще - были помечены как TODO и просто логировались, то есть
"забыли пароль" не работал ни для одного пользователя: токен
генерировался и сохранялся в Redis, но никак не попадал к пользователю.

Использует стандартный smtplib (не aiosmtplib - его нет ни в одном из
app/requirements/*.txt, а добавлять новую обязательную зависимость ради
опциональной фичи не входит в объём этого фикса), синхронный вызов
уводится в отдельный поток через asyncio.to_thread, чтобы не блокировать
event loop.

SMTP_HOST не задан - валидное состояние "email не настроен" (см.
Settings.SMTP_ENABLED), а не ошибка: письмо в этом случае просто
логируется и не отправляется, по аналогии с тем, как STT намеренно
необязателен для установки.
"""

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings
from app.core.logger import logger


class EmailSendError(Exception):
    """Не удалось отправить письмо через настроенный SMTP."""
    pass


def _send_sync(to_email: str, subject: str, text_body: str, html_body: Optional[str], smtp_config: dict) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{smtp_config['from_email']}>"
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_config['host'], smtp_config['port'], timeout=settings.SMTP_TIMEOUT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if smtp_config['username']:
            smtp.login(smtp_config['username'], smtp_config['password'] or "")
        smtp.send_message(message)


async def send_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """
    Отправить письмо через настроенный SMTP.

    Returns:
        True, если письмо отправлено. False, если SMTP не настроен
        (SMTP_ENABLED == False) - это не ошибка, вызывающий код должен
        просто продолжить работу (регистрация/сброс пароля не должны
        падать из-за отсутствия почтового сервера в песочнице/деве).

    Raises:
        EmailSendError: SMTP настроен, но отправка реально не удалась
        (неверные креды, сервер недоступен и т.п.) - в отличие от
        "не настроен", это ошибка, которую вызывающий код должен видеть.
    """
    # notifications.email_enabled/smtp_host/smtp_port/smtp_username/
    # smtp_password/from_email (Настройки → Уведомления) раньше сохранялись
    # в БД, но эта функция всегда использовала только settings.SMTP_* из
    # .env - значения из веб-интерфейса ни на что не влияли. Читаем их
    # здесь заново на каждую отправку (SMTP-конфиг не кешируется в памяти
    # нигде), с тем же запасным вариантом на .env при любом сбое.
    try:
        from app.services import get_settings_service
        settings_service = get_settings_service()
        email_enabled = await settings_service.get_setting_value("notifications.email_enabled")
        smtp_config = {
            'host': await settings_service.get_setting_value("notifications.smtp_host") or settings.SMTP_HOST,
            'port': await settings_service.get_setting_value("notifications.smtp_port") or settings.SMTP_PORT,
            'username': await settings_service.get_setting_value("notifications.smtp_username") or settings.SMTP_USER,
            'password': await settings_service.get_setting_value("notifications.smtp_password") or settings.SMTP_PASSWORD,
            'from_email': await settings_service.get_setting_value("notifications.from_email") or settings.SMTP_FROM_EMAIL,
        }
    except Exception:
        email_enabled = settings.SMTP_ENABLED
        smtp_config = {
            'host': settings.SMTP_HOST,
            'port': settings.SMTP_PORT,
            'username': settings.SMTP_USER,
            'password': settings.SMTP_PASSWORD,
            'from_email': settings.SMTP_FROM_EMAIL,
        }

    if not smtp_config['host']:
        logger.info(f"SMTP не настроен (host пуст) - письмо '{subject}' для {to_email} не отправлено")
        return False

    # notifications.email_enabled по умолчанию False - если проверять его
    # в одиночку, любая уже работающая через .env отправка (SMTP_HOST
    # задан, settings.SMTP_ENABLED уже True) сломалась бы прямо сейчас,
    # для всех, кто просто ни разу не открывал этот тумблер в интерфейсе.
    # settings.SMTP_ENABLED в условии - гарантия, что уже настроенный через
    # .env SMTP продолжает отправлять как раньше; email_enabled - новый
    # способ явно включить отправку для конфигурации, заданной ТОЛЬКО
    # через веб (без .env вообще).
    if not email_enabled and not settings.SMTP_ENABLED:
        logger.info(f"Email-уведомления отключены администратором - письмо '{subject}' для {to_email} не отправлено")
        return False

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, text_body, html_body, smtp_config)
    except Exception as e:
        logger.error(f"Не удалось отправить письмо '{subject}' для {to_email}: {e}")
        raise EmailSendError(str(e)) from e

    logger.info(f"Письмо '{subject}' отправлено на {to_email}")
    return True
