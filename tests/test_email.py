"""
Regression tests for app.utils.email.send_email.

Before this, app/services/user.py's forgot_password() generated a reset
token, saved it to Redis, and then just logged "Токен восстановления
создан" - the token never reached the user by any channel, so "forgot
password" was a complete no-op from the user's point of view. Same for
the welcome email on user creation. app.utils.email is the single place
that now actually sends mail, and app/services/user.py wires both flows
into it.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.utils import email as email_module


@pytest.mark.asyncio
async def test_send_email_is_a_noop_when_smtp_not_configured(monkeypatch):
    # SMTP_HOST unset is a valid "email not configured" state (see
    # Settings.SMTP_ENABLED) - not an error. Callers (password reset, user
    # creation) must not fail just because no mail server is available in
    # this environment.
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", None)

    with patch("smtplib.SMTP") as smtp_cls:
        sent = await email_module.send_email("user@example.com", "Subject", "Body")

    assert sent is False
    smtp_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_sends_via_smtp_when_configured(monkeypatch):
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(email_module.settings, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(email_module.settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(email_module.settings, "SMTP_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_FROM_NAME", "AutoDialer")

    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_cm.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=smtp_cm) as smtp_cls:
        sent = await email_module.send_email("user@example.com", "Hello", "Body text")

    assert sent is True
    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=email_module.settings.SMTP_TIMEOUT)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("bot@example.com", "secret")
    smtp_instance.send_message.assert_called_once()
    sent_message = smtp_instance.send_message.call_args.args[0]
    assert sent_message["To"] == "user@example.com"
    assert sent_message["Subject"] == "Hello"


@pytest.mark.asyncio
async def test_send_email_raises_email_send_error_when_smtp_fails(monkeypatch):
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_USER", None)

    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        with pytest.raises(email_module.EmailSendError):
            await email_module.send_email("user@example.com", "Hello", "Body")
