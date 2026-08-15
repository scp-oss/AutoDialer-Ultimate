"""
Regression tests for app._service_error_status_code / _service_error_handler.

Found live via docker compose: app/api/*.py routers never catch the ~50
custom exception classes app/services/*.py defines (UserNotFoundError,
InvalidCredentialsError, CampaignValidationError, ...), and no exception
handler existed anywhere to convert them into HTTP responses either - so
every business error anywhere in the API (wrong password, "not found",
validation, conflict) fell through to FastAPI's default handling and
became a bare 500 Internal Server Error instead of the correct
401/403/404/409/422. Confirmed with real requests against the full stack
(postgres+redis+asterisk+backend+nginx via `docker compose up`):
POST /api/auth/login with a wrong password returned 500 with no useful
detail; after this fix it returns 401 {"detail": "..."} .

ConnectionPool.acquire() (app/core/database.py) had a related, deeper bug:
its blanket `except Exception` around the *entire* `async with` block body
caught business exceptions raised by the caller's own code (not just
genuine connection failures) and re-wrapped them as
QueryError("Failed to acquire connection: ..."), destroying both the
original exception type and message. That is covered by live testing
(ROADMAP.md), not exercised here since it requires a real asyncpg pool -
this file covers only the HTTP-status mapping layer, which is pure logic.
"""

import json

import pytest
from fastapi import Request

from app import _service_error_status_code, _service_error_handler
from app.services.blacklist import BlacklistNotFoundError, BlacklistAlreadyExistsError, BlacklistError
from app.core.database import UniqueViolationError, ForeignKeyViolationError


def _fake_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


@pytest.mark.parametrize(
    "exc, expected_status",
    [
        (BlacklistNotFoundError("x"), 404),
        (BlacklistAlreadyExistsError("x"), 409),
        (BlacklistError("x"), 400),  # base class of a domain - business rule, not a bug
    ],
)
def test_service_error_status_code_maps_by_class_name_suffix(exc, expected_status):
    assert _service_error_status_code(exc) == expected_status


def test_service_error_status_code_unmatched_suffix_falls_back_to_400():
    class WeirdError(Exception):
        pass

    assert _service_error_status_code(WeirdError("x")) == 400


async def test_service_error_handler_converts_service_exception_to_json():
    exc = BlacklistNotFoundError("Номер не найден в чёрном списке")
    response = await _service_error_handler(_fake_request(), exc)

    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "Номер не найден в чёрном списке"}


async def test_service_error_handler_maps_db_constraint_violations_to_409():
    for exc in (UniqueViolationError("dup"), ForeignKeyViolationError("fk")):
        response = await _service_error_handler(_fake_request(), exc)
        assert response.status_code == 409


async def test_service_error_handler_reraises_exceptions_outside_app_services():
    class NotAServiceError(Exception):
        pass

    with pytest.raises(NotAServiceError):
        await _service_error_handler(_fake_request(), NotAServiceError("boom"))
