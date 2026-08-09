"""
Unit tests for app.utils.phone - the single source of truth for the
Russian phone numbering plan (normalize_phone/validate_phone_number/
format_phone_display), consolidated from 6+ near-duplicate implementations
across app/models/*.py and app/services/*.py (see ROADMAP.md §3.9).

Pure functions, no DB/Redis - runs in any environment.
"""

from app.utils.phone import (
    format_phone_display,
    normalize_phone,
    validate_phone_number,
)


class TestNormalizePhone:
    def test_empty_and_none(self):
        assert normalize_phone("") == ""
        assert normalize_phone(None) == ""

    def test_leading_8_becomes_7(self):
        assert normalize_phone("89991234567") == "79991234567"

    def test_already_7_prefixed_unchanged(self):
        assert normalize_phone("79991234567") == "79991234567"

    def test_bare_10_digit_mobile_gets_country_code(self):
        assert normalize_phone("9991234567") == "79991234567"

    def test_bare_10_digit_non_mobile_left_as_is(self):
        # Only bare 10-digit numbers starting with "9" are treated as
        # mobile and auto-prefixed; other 10-digit numbers (e.g. landline
        # codes) are left untouched by normalize_phone itself - display
        # formatting (format_phone_display) is what adds "+7" for those.
        assert normalize_phone("4951234567") == "4951234567"

    def test_strips_formatting_characters(self):
        assert normalize_phone("+7 (999) 123-45-67") == "79991234567"
        assert normalize_phone("8-999-123-45-67") == "79991234567"
        assert normalize_phone("8 (999) 123-45-67") == "79991234567"

    def test_non_ru_international_number_untouched(self):
        # 12-digit number, doesn't match any RU-specific branch
        assert normalize_phone("123456789012") == "123456789012"


class TestValidatePhoneNumber:
    def test_valid_ru_mobile(self):
        assert validate_phone_number("79991234567") is True
        assert validate_phone_number("89991234567") is True
        assert validate_phone_number("9991234567") is True

    def test_too_short_rejected(self):
        assert validate_phone_number("12345") is False

    def test_ru_number_wrong_length_rejected(self):
        # Starts with 7 but not 11 digits total
        assert validate_phone_number("799912345") is False

    def test_ru_operator_code_starting_with_0_rejected(self):
        assert validate_phone_number("70991234567") is False

    def test_ru_operator_code_starting_with_1_rejected(self):
        assert validate_phone_number("71991234567") is False

    def test_international_number_within_15_digits_accepted(self):
        assert validate_phone_number("123456789012") is True

    def test_too_long_rejected(self):
        assert validate_phone_number("1234567890123456") is False

    def test_empty_rejected(self):
        assert validate_phone_number("") is False


class TestFormatPhoneDisplay:
    def test_formats_11_digit_ru_number(self):
        assert format_phone_display("79991234567") == "+7 (999) 123-45-67"

    def test_formats_leading_8_as_plus_7(self):
        assert format_phone_display("89991234567") == "+7 (999) 123-45-67"

    def test_formats_bare_10_digit_mobile_with_plus_7(self):
        # Regression: this branch used to omit the "+7" prefix entirely
        # for bare 10-digit numbers, showing e.g. "(999) 123-45-67".
        assert format_phone_display("9991234567") == "+7 (999) 123-45-67"

    def test_formats_bare_10_digit_non_mobile_with_plus_7(self):
        assert format_phone_display("4951234567") == "+7 (495) 123-45-67"

    def test_empty_returns_empty(self):
        assert format_phone_display("") == ""
        assert format_phone_display(None) == ""

    def test_other_length_gets_plus_prefix_only(self):
        assert format_phone_display("123456789012") == "+123456789012"
