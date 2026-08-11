"""
Unit tests for app.services.blacklist.BlacklistService - business logic
that never got any test coverage because it talks to Postgres/Redis
(app/core/database.py: ConnectionPool.acquire() -> raw asyncpg connection,
app/core/redis.py: RedisClient). Here both are replaced with lightweight
in-memory fakes so the service logic (branching, error types, phone
normalization, sequencing of DB/Redis calls) is verified without any real
infrastructure. asyncio_mode = "auto" (pyproject.toml).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.blacklist import (
    BlacklistAddRequest,
    BlacklistBulkAddRequest,
    BlacklistReason,
    BlacklistSource,
    BlacklistStatus,
)
from app.services.blacklist import (
    BlacklistAlreadyExistsError,
    BlacklistNotFoundError,
    BlacklistService,
    BlacklistValidationError,
)


class FakeConnection:
    def __init__(self):
        self.fetchrow = AsyncMock(return_value=None)
        self.fetchval = AsyncMock(return_value=None)
        self.fetch = AsyncMock(return_value=[])
        self.execute = AsyncMock(return_value="UPDATE 0")


class _AcquireCM:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCM(self._conn)


class FakeRedis:
    def __init__(self, blacklisted=False):
        self.add_to_blacklist = AsyncMock(return_value=None)
        self.remove_from_blacklist = AsyncMock(return_value=None)
        self.is_blacklisted = AsyncMock(return_value=blacklisted)


def make_row(**overrides):
    row = {
        "id": 42,
        "phone": "79991234567",
        "reason": BlacklistReason.SPAM.value,
        "reason_details": None,
        "status": BlacklistStatus.ACTIVE.value,
        "expires_at": None,
        "source": BlacklistSource.MANUAL.value,
        "notes": None,
        "created_by": 1,
        "created_by_name": "admin",
        "removed_at": None,
        "removed_by": None,
        "removed_reason": None,
        "times_called_before": 0,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    row.update(overrides)
    return row


def make_service(conn=None, redis=None):
    conn = conn or FakeConnection()
    redis = redis or FakeRedis()
    return BlacklistService(FakePool(conn), redis), conn, redis


async def test_add_to_blacklist_rejects_invalid_phone():
    service, conn, redis = make_service()
    request = BlacklistAddRequest.model_construct(
        phone="not-a-phone",
        reason=BlacklistReason.OTHER,
        reason_details=None,
        expires_at=None,
        source=BlacklistSource.MANUAL,
        notes=None,
        tags=[],
    )

    with pytest.raises(BlacklistValidationError):
        await service.add_to_blacklist(request)

    conn.fetchrow.assert_not_called()
    redis.add_to_blacklist.assert_not_called()


async def test_add_to_blacklist_raises_when_already_active():
    conn = FakeConnection()
    conn.fetchrow.return_value = {"id": 1, "status": BlacklistStatus.ACTIVE.value}
    service, conn, redis = make_service(conn=conn)

    request = BlacklistAddRequest(phone="+7 999 123-45-67", reason=BlacklistReason.SPAM)

    with pytest.raises(BlacklistAlreadyExistsError):
        await service.add_to_blacklist(request)

    redis.add_to_blacklist.assert_not_called()


async def test_add_to_blacklist_creates_new_entry_and_normalizes_phone():
    conn = FakeConnection()
    conn.fetchrow.side_effect = [
        None,  # existence check: nothing found
        make_row(id=42, phone="79991234567"),  # _get_blacklist_by_id
    ]
    conn.fetchval.return_value = 42  # INSERT ... RETURNING id
    service, conn, redis = make_service(conn=conn)

    request = BlacklistAddRequest(phone="+7 (999) 123-45-67", reason=BlacklistReason.SPAM)
    result = await service.add_to_blacklist(request, user_id=1)

    assert result.id == 42
    assert result.phone == "79991234567"
    redis.add_to_blacklist.assert_awaited_once_with("79991234567")


async def test_add_to_blacklist_reactivates_removed_entry():
    conn = FakeConnection()
    conn.fetchrow.side_effect = [
        {"id": 7, "status": BlacklistStatus.REMOVED.value},  # existence check
        make_row(id=7),  # _get_blacklist_by_id
    ]
    service, conn, redis = make_service(conn=conn)

    request = BlacklistAddRequest(phone="+79991234567", reason=BlacklistReason.SPAM)
    result = await service.add_to_blacklist(request)

    assert result.id == 7
    # Reactivation path uses UPDATE, not INSERT ... RETURNING id
    conn.fetchval.assert_not_called()
    redis.add_to_blacklist.assert_awaited_once()


async def test_remove_from_blacklist_raises_not_found():
    service, conn, redis = make_service()

    with pytest.raises(BlacklistNotFoundError):
        await service.remove_from_blacklist(999)

    redis.remove_from_blacklist.assert_not_called()


async def test_remove_from_blacklist_already_removed_is_a_noop():
    conn = FakeConnection()
    conn.fetchrow.return_value = {
        "id": 5,
        "phone": "79991234567",
        "status": BlacklistStatus.REMOVED.value,
    }
    service, conn, redis = make_service(conn=conn)

    result = await service.remove_from_blacklist(5)

    assert result.success is False
    assert result.removed is False
    redis.remove_from_blacklist.assert_not_called()


async def test_remove_from_blacklist_success():
    conn = FakeConnection()
    conn.fetchrow.return_value = {
        "id": 5,
        "phone": "79991234567",
        "status": BlacklistStatus.ACTIVE.value,
    }
    service, conn, redis = make_service(conn=conn)

    result = await service.remove_from_blacklist(5, user_id=1, reason="test")

    assert result.success is True
    assert result.removed is True
    redis.remove_from_blacklist.assert_awaited_once_with("79991234567")


async def test_check_phone_short_circuits_on_redis_miss_without_db_query():
    redis = FakeRedis(blacklisted=False)
    conn = FakeConnection()
    service, conn, redis = make_service(conn=conn, redis=redis)

    result = await service.check_phone("+79991234567")

    assert result.is_blacklisted is False
    conn.fetchrow.assert_not_called()


async def test_check_phone_queries_db_on_redis_hit():
    redis = FakeRedis(blacklisted=True)
    conn = FakeConnection()
    conn.fetchrow.side_effect = [
        {"id": 42},  # _get_blacklist_by_phone lookup
        make_row(id=42, status=BlacklistStatus.ACTIVE.value),  # _get_blacklist_by_id
    ]
    service, conn, redis = make_service(conn=conn, redis=redis)

    result = await service.check_phone("+79991234567")

    assert result.is_blacklisted is True
    assert result.record.id == 42


async def test_check_phone_invalid_number_never_touches_redis():
    redis = FakeRedis()
    service, conn, redis = make_service(redis=redis)

    result = await service.check_phone("abc")

    assert result.is_blacklisted is False
    redis.is_blacklisted.assert_not_called()


async def test_cleanup_expired_parses_update_count_from_command_tag():
    conn = FakeConnection()
    conn.execute.return_value = "UPDATE 3"
    conn.fetchval.return_value = 10  # get_active_count() called after cleanup
    service, conn, redis = make_service(conn=conn)

    cleaned = await service.cleanup_expired()

    assert cleaned == 3


async def test_cleanup_expired_returns_zero_when_nothing_matched():
    conn = FakeConnection()
    conn.execute.return_value = "UPDATE 0"
    service, conn, redis = make_service(conn=conn)

    cleaned = await service.cleanup_expired()

    assert cleaned == 0


async def test_get_active_count_delegates_to_fetchval():
    conn = FakeConnection()
    conn.fetchval.return_value = 17
    service, conn, redis = make_service(conn=conn)

    count = await service.get_active_count()

    assert count == 17


async def test_bulk_add_skips_existing_numbers():
    conn = FakeConnection()
    # Existence check finds an already-active row -> the number is skipped.
    conn.fetchrow.return_value = {"id": 1}
    conn.fetchval.return_value = 3  # get_active_count() called after the loop
    service, conn, redis = make_service(conn=conn)

    request = BlacklistBulkAddRequest(
        phones=["+79991234567"],
        reason=BlacklistReason.SPAM,
        source=BlacklistSource.IMPORT,
        skip_invalid=True,
        skip_existing=True,
    )
    result = await service.bulk_add_to_blacklist(request)

    assert result.total == 1
    assert result.skipped == 1
    assert result.added == 0


async def test_bulk_add_counts_invalid_numbers():
    # BlacklistBulkAddRequest.phones is normalized/filtered by a pydantic
    # field_validator before the service ever sees it (see
    # app.models.blacklist.BlacklistBulkAddRequest.normalize_phones), so a
    # genuinely invalid number never reaches bulk_add_to_blacklist() through
    # the normal constructor. model_construct() bypasses that validator to
    # exercise the service's own invalid-number handling directly.
    conn = FakeConnection()
    conn.fetchrow.return_value = None  # no existing entry for the valid number
    conn.fetchval.side_effect = [42, 5]  # INSERT ... RETURNING id, then get_active_count()
    service, conn, redis = make_service(conn=conn)

    request = BlacklistBulkAddRequest.model_construct(
        phones=["not-a-phone", "+79991234567"],
        reason=BlacklistReason.SPAM,
        reason_details=None,
        expires_at=None,
        source=BlacklistSource.IMPORT,
        skip_existing=True,
        skip_invalid=True,
        tags=[],
    )
    result = await service.bulk_add_to_blacklist(request)

    assert result.total == 2
    assert result.invalid == 1
    assert result.added == 1
