"""Unit tests for app.core.security - pure functions, no DB/Redis needed."""

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
)


def test_password_hash_roundtrip():
    hashed = hash_password("Sup3rSecret!")
    assert hashed != "Sup3rSecret!"
    assert verify_password("Sup3rSecret!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token({"sub": "42", "username": "admin", "role": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["username"] == "admin"
    assert payload["type"] == "access"
