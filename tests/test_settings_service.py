"""
Unit tests for app.services.settings.SettingsService - business logic
that never got any test coverage because it talks to Postgres/Redis
(app/core/database.py: ConnectionPool.acquire() -> raw asyncpg connection,
app/core/redis.py: RedisClient). Here both are replaced with lightweight
in-memory fakes so the service logic (validation branching, caching,
readonly enforcement, idempotent seeding) is verified without any real
infrastructure. asyncio_mode = "auto" (pyproject.toml).

Mocking the DB layer cannot catch SQL-level bugs (e.g. the
AmbiguousColumnError found in get_setting() during live testing, see
ROADMAP.md §3.0 Баг №10) - these tests cover the pure business logic that
mocks CAN verify: value validation/coercion, readonly/not-found errors,
cache read-through, and initialize_defaults() idempotency.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.settings import (
    SettingDefinition,
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingsService,
    SettingValidationError,
    SYSTEM_SETTINGS,
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
    def __init__(self):
        self._store = {}
        self.get = AsyncMock(side_effect=self._get)
        self.setex = AsyncMock(side_effect=self._setex)
        self.delete = AsyncMock(side_effect=self._delete)
        self.scan = AsyncMock(return_value=(0, []))

    async def _get(self, key):
        return self._store.get(key)

    async def _setex(self, key, ex, value):
        self._store[key] = value

    async def _delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                removed += 1
        return removed


def make_service(conn=None, redis=None):
    conn = conn or FakeConnection()
    redis = redis or FakeRedis()
    return SettingsService(FakePool(conn), redis), conn, redis


# =============================================
# _validate_and_parse - pure validation logic
# =============================================
def make_definition(**overrides):
    base = dict(key="test.key", value_type="string")
    base.update(overrides)
    return SettingDefinition(**base)


async def test_validate_and_parse_string_rejects_disallowed_value():
    service, _, _ = make_service()
    definition = make_definition(value_type="string", allowed_values=["ru", "en"])

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("fr", definition)


async def test_validate_and_parse_string_accepts_allowed_value():
    service, _, _ = make_service()
    definition = make_definition(value_type="string", allowed_values=["ru", "en"])

    assert service._validate_and_parse("en", definition) == "en"


async def test_validate_and_parse_int_enforces_min_and_max():
    service, _, _ = make_service()
    definition = make_definition(value_type="int", min_value=1, max_value=500)

    assert service._validate_and_parse("50", definition) == 50

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("0", definition)

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("501", definition)


async def test_validate_and_parse_int_rejects_non_numeric():
    service, _, _ = make_service()
    definition = make_definition(value_type="int", min_value=1, max_value=500)

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("not-a-number", definition)


async def test_validate_and_parse_float_enforces_min_and_max():
    service, _, _ = make_service()
    definition = make_definition(value_type="float", min_value=0.1, max_value=10.0)

    assert service._validate_and_parse("5.5", definition) == 5.5

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("0.01", definition)


async def test_validate_and_parse_bool_accepts_common_truthy_strings():
    service, _, _ = make_service()
    definition = make_definition(value_type="bool")

    for truthy in ("true", "1", "yes", "on", "TRUE"):
        assert service._validate_and_parse(truthy, definition) is True

    for falsy in ("false", "0", "no", "off", ""):
        assert service._validate_and_parse(falsy, definition) is False


async def test_validate_and_parse_list_accepts_json_and_csv():
    service, _, _ = make_service()
    definition = make_definition(value_type="list")

    assert service._validate_and_parse('["a", "b"]', definition) == ["a", "b"]
    assert service._validate_and_parse("a, b, c", definition) == ["a", "b", "c"]


async def test_validate_and_parse_list_rejects_malformed_json():
    service, _, _ = make_service()
    definition = make_definition(value_type="list")

    # A leading "[" routes through json.loads(); malformed JSON there
    # raises JSONDecodeError, a ValueError subclass the outer except
    # re-raises as SettingValidationError.
    with pytest.raises(SettingValidationError):
        service._validate_and_parse("[not valid json", definition)


async def test_validate_and_parse_enforces_regex():
    service, _, _ = make_service()
    definition = make_definition(value_type="string", validation_regex=r"^\d{3}-\d{4}$")

    assert service._validate_and_parse("123-4567", definition) == "123-4567"

    with pytest.raises(SettingValidationError):
        service._validate_and_parse("not-a-match", definition)


# =============================================
# update_setting - error branches + happy path
# =============================================
async def test_update_setting_rejects_unknown_key():
    service, _, _ = make_service()

    with pytest.raises(SettingNotFoundError):
        await service.update_setting("does.not.exist", "value")


async def test_update_setting_rejects_readonly_key():
    service, _, _ = make_service()

    with pytest.raises(SettingReadOnlyError):
        await service.update_setting("security.password_min_length", "10")


async def test_update_setting_rejects_invalid_value_before_touching_db():
    service, conn, _ = make_service()

    with pytest.raises(SettingValidationError):
        await service.update_setting("dialer.max_calls", "not-a-number")

    conn.execute.assert_not_called()


async def test_update_setting_writes_value_and_invalidates_cache():
    service, conn, redis = make_service()
    conn.fetchrow.return_value = {"updated_at": None, "updated_by": None, "updated_by_name": None}

    await service.update_setting("dialer.max_calls", "75", user_id=1)

    conn.execute.assert_any_call(
        "\n                INSERT INTO settings (key, value, updated_by, updated_at)\n"
        "                VALUES ($1, $2, $3, NOW())\n"
        "                ON CONFLICT (key) DO UPDATE SET\n"
        "                    value = EXCLUDED.value,\n"
        "                    updated_by = EXCLUDED.updated_by,\n"
        "                    updated_at = NOW()\n            ",
        "dialer.max_calls",
        "75",
        1,
    )
    # Cache invalidation happens before update_setting() re-reads the
    # setting to build its response - assert on the delete call itself
    # rather than final cache state, since the re-read repopulates the
    # cache from the (fake, non-persistent) DB layer.
    redis.delete.assert_any_call("setting:dialer.max_calls")


async def test_update_setting_applies_on_change_callback():
    service, conn, _ = make_service()
    conn.fetchrow.return_value = {"updated_at": None, "updated_by": None, "updated_by_name": None}

    class FakeDialer:
        max_calls = None

    dialer = FakeDialer()
    service.dialer_manager = dialer

    await service.update_setting("dialer.max_calls", "42")

    assert dialer.max_calls == 42


async def test_update_setting_swallows_callback_errors():
    service, conn, _ = make_service()
    conn.fetchrow.return_value = {"updated_at": None, "updated_by": None, "updated_by_name": None}

    async def boom(value):
        raise RuntimeError("callback exploded")

    service._change_callbacks["update_dialer_max_calls"] = boom

    # Should not raise even though the on_change callback fails.
    result = await service.update_setting("dialer.max_calls", "42")
    assert result.key == "dialer.max_calls"


# =============================================
# get_setting_value - cache read-through
# =============================================
async def test_get_setting_value_returns_cached_value_without_db_hit():
    service, conn, redis = make_service()
    await redis.setex("setting:system.name", 300, json.dumps("Cached Name"))

    value = await service.get_setting_value("system.name")

    assert value == "Cached Name"
    conn.fetchval.assert_not_called()


async def test_get_setting_value_falls_back_to_default_when_not_in_db():
    service, conn, redis = make_service()
    conn.fetchval.return_value = None

    value = await service.get_setting_value("dialer.max_calls")

    assert value == 50  # SYSTEM_SETTINGS default_value
    # Falling back to the default still populates the cache.
    assert json.loads(redis._store["setting:dialer.max_calls"]) == 50


async def test_get_setting_value_parses_db_value_by_declared_type():
    service, conn, _ = make_service()
    conn.fetchval.return_value = "123"

    value = await service.get_setting_value("dialer.max_calls")

    assert value == 123
    assert isinstance(value, int)


async def test_get_setting_value_rejects_unknown_key():
    service, _, _ = make_service()

    with pytest.raises(SettingNotFoundError):
        await service.get_setting_value("does.not.exist")


# =============================================
# initialize_defaults - idempotent seeding
# =============================================
async def test_initialize_defaults_creates_only_missing_keys():
    service, conn, _ = make_service()
    existing_keys = set(list(SYSTEM_SETTINGS.keys())[:5])
    conn.fetchval = AsyncMock(side_effect=lambda query, key: 1 if key in existing_keys else None)

    created = await service.initialize_defaults()

    assert created == len(SYSTEM_SETTINGS) - len(existing_keys)


async def test_initialize_defaults_is_a_noop_when_everything_exists():
    service, conn, _ = make_service()
    conn.fetchval.return_value = 1

    created = await service.initialize_defaults()

    assert created == 0
    conn.execute.assert_not_called()


# =============================================
# get_categories - grouping/count logic
# =============================================
async def test_get_categories_counts_settings_per_category():
    service, _, _ = make_service()

    categories = await service.get_categories()

    total_counted = sum(c["count"] for c in categories)
    assert total_counted == len(SYSTEM_SETTINGS)
    names = {c["name"] for c in categories}
    assert "dialer" in names
    assert "security" in names
