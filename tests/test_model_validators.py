"""
Unit tests for Pydantic request-model validators in app/models/*.py.

These are pure schema-validation tests (model construction only, no DB/
Redis, no app fixture) - they exercise field_validator/model_validator
logic directly, the same way FastAPI would when parsing a request body.
"""

import pytest
from pydantic import ValidationError

from app.models.blacklist import BlacklistAddRequest
from app.models.contact import ContactCreateRequest
from app.models.user import UserCreateRequest


class TestUserCreateRequest:
    def test_valid_user_accepted(self):
        u = UserCreateRequest(username="ivanov", password="SecurePass123", role="viewer")
        assert u.username == "ivanov"

    def test_username_lowercased_and_stripped(self):
        u = UserCreateRequest(username=" Ivanov ", password="SecurePass123", role="viewer")
        assert u.username == "ivanov"

    @pytest.mark.parametrize("forbidden", ["admin", "Administrator", "ROOT", "system", "autodialer", "noreply"])
    def test_forbidden_username_rejected(self, forbidden):
        with pytest.raises(ValidationError):
            UserCreateRequest(username=forbidden, password="SecurePass123", role="viewer")

    def test_password_too_short_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov", password="Ab1", role="viewer")

    def test_password_without_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov", password="lowercase123", role="viewer")

    def test_password_without_lowercase_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov", password="UPPERCASE123", role="viewer")

    def test_password_without_digit_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov", password="NoDigitsHere", role="viewer")

    def test_password_equal_to_username_rejected(self):
        # Regression: validate_password_strength's docstring promised this
        # check "will be done in a model_validator", but no such validator
        # existed - a password identical to (or containing) the username
        # passed validation entirely. See ROADMAP.md.
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov123", password="Ivanov123", role="viewer")

    def test_password_containing_username_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="ivanov", password="MyIvanovPass1", role="viewer")

    def test_password_unrelated_to_username_accepted(self):
        u = UserCreateRequest(username="ivanov", password="SecurePass123", role="viewer")
        assert u.password == "SecurePass123"

    def test_email_lowercased(self):
        u = UserCreateRequest(
            username="ivanov", password="SecurePass123", email="Ivanov@Example.COM", role="viewer"
        )
        assert u.email == "ivanov@example.com"


class TestContactCreateRequest:
    def test_valid_phone_normalized(self):
        c = ContactCreateRequest(phone="8 (999) 123-45-67")
        assert c.phone == "79991234567"

    def test_invalid_phone_rejected(self):
        with pytest.raises(ValidationError):
            ContactCreateRequest(phone="123")

    def test_empty_phone_rejected(self):
        with pytest.raises(ValidationError):
            ContactCreateRequest(phone="")

    def test_secondary_phone_normalized(self):
        c = ContactCreateRequest(phone="+79991234567", phone2="89997654321")
        assert c.phone2 == "79997654321"

    def test_email_lowercased(self):
        c = ContactCreateRequest(phone="+79991234567", email="Ivan@Example.COM")
        assert c.email == "ivan@example.com"

    def test_name_stripped(self):
        c = ContactCreateRequest(phone="+79991234567", name="  Иван Петров  ")
        assert c.name == "Иван Петров"


class TestBlacklistAddRequest:
    def test_valid_phone_normalized(self):
        b = BlacklistAddRequest(phone="8-999-123-45-67")
        assert b.phone == "79991234567"

    def test_invalid_operator_code_rejected(self):
        # Regression: this used to only check len(normalized) >= 10, which
        # accepted invalid operator/region codes like "70..."/"71...".
        with pytest.raises(ValidationError):
            BlacklistAddRequest(phone="70991234567")

    def test_too_short_rejected(self):
        with pytest.raises(ValidationError):
            BlacklistAddRequest(phone="12345")

    def test_empty_phone_rejected(self):
        with pytest.raises(ValidationError):
            BlacklistAddRequest(phone="")
