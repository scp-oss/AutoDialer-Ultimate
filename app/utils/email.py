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


def _send_sync(to_email: str, subject: str, text_body: str, html_body: Optional[str]) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
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
    if not settings.SMTP_ENABLED:
        logger.info(f"SMTP не настроен (SMTP_HOST пуст) - письмо '{subject}' для {to_email} не отправлено")
        return False

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, text_body, html_body)
    except Exception as e:
        logger.error(f"Не удалось отправить письмо '{subject}' для {to_email}: {e}")
        raise EmailSendError(str(e)) from e

    logger.info(f"Письмо '{subject}' отправлено на {to_email}")
    return True
