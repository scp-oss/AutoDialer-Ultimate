"""
Unit tests for app.utils.circuit_breaker.CircuitBreaker.

Pure in-memory state machine (asyncio only, no DB/Redis/AMI) that guards
every call to those external services elsewhere in the app - worth testing
directly without any infrastructure. asyncio_mode = "auto" (pyproject.toml)
lets these be plain `async def test_...` functions.
"""

import asyncio

import pytest

from app.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitTimeoutError,
)


def make_breaker(**overrides):
    defaults = dict(
        name="test",
        failure_threshold=3,
        recovery_timeout=5.0,
        success_threshold=2,
        exponential_backoff=False,
        timeout=1.0,
    )
    defaults.update(overrides)
    return CircuitBreaker(**defaults)


async def failing():
    raise RuntimeError("boom")


async def ok():
    return "ok"


async def test_starts_closed_with_zero_failures():
    cb = make_breaker()
    assert cb.is_closed
    assert cb.failure_count == 0


async def test_opens_after_failure_threshold_failures():
    cb = make_breaker(failure_threshold=3)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(failing)
    assert cb.is_open


async def test_open_circuit_rejects_without_invoking_func():
    cb = make_breaker(failure_threshold=1, recovery_timeout=5.0)
    with pytest.raises(RuntimeError):
        await cb.call(failing)
    assert cb.is_open

    invoked = []

    async def tracked():
        invoked.append(1)
        return "should not run"

    with pytest.raises(CircuitOpenError):
        await cb.call(tracked)
    assert invoked == []


async def test_success_decrements_failure_count_while_closed():
    cb = make_breaker(failure_threshold=5)
    with pytest.raises(RuntimeError):
        await cb.call(failing)
    with pytest.raises(RuntimeError):
        await cb.call(failing)
    assert cb.failure_count == 2

    await cb.call(ok)
    assert cb.is_closed
    assert cb.failure_count == 1


async def test_recovery_after_successes_is_not_undone_by_next_failure():
    """
    Regression: _record_success() used to decrement the failure_count field
    without removing the matching entry from the internal sliding-window
    list (_failure_timestamps). _record_failure() always recomputes
    failure_count as len(_failure_timestamps), so the "recovery" a success
    appeared to grant was cosmetic - a single failure right after several
    successes would jump failure_count straight back to the stale
    pre-recovery total (and could open the circuit outright) instead of
    incrementing from the value callers just observed via failure_count/
    get_status(). Fixed by popping the oldest timestamp alongside the
    failure_count decrement, keeping the two in sync on every path.
    """
    cb = make_breaker(failure_threshold=5)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(failing)
    assert cb.failure_count == 3

    for _ in range(3):
        await cb.call(ok)
    assert cb.is_closed
    assert cb.failure_count == 0

    with pytest.raises(RuntimeError):
        await cb.call(failing)
    assert cb.failure_count == 1
    assert cb.is_closed


async def test_transitions_to_half_open_after_recovery_timeout_and_closes_on_success():
    cb = make_breaker(failure_threshold=1, recovery_timeout=0.05, success_threshold=2)
    with pytest.raises(RuntimeError):
        await cb.call(failing)
    assert cb.is_open

    await asyncio.sleep(0.08)

    assert await cb.call(ok) == "ok"
    assert cb.is_half_open  # first probe success, success_threshold=2 not yet reached

    assert await cb.call(ok) == "ok"
    assert cb.is_closed
    assert cb.failure_count == 0


async def test_failure_during_half_open_reopens_immediately():
    cb = make_breaker(failure_threshold=1, recovery_timeout=0.05)
    with pytest.raises(RuntimeError):
        await cb.call(failing)
    await asyncio.sleep(0.08)

    with pytest.raises(RuntimeError):
        await cb.call(failing)
    assert cb.is_open


async def test_call_timeout_raises_circuit_timeout_error_and_counts_as_failure():
    cb = make_breaker(failure_threshold=2, timeout=0.02, recovery_timeout=5.0)

    async def slow():
        await asyncio.sleep(1.0)

    with pytest.raises(CircuitTimeoutError):
        await cb.call(slow)
    assert cb.failure_count == 1
    assert cb.is_closed

    with pytest.raises(CircuitTimeoutError):
        await cb.call(slow)
    assert cb.is_open


async def test_context_manager_records_success_and_failure():
    cb = make_breaker(failure_threshold=2)

    async with cb:
        pass
    assert cb.is_closed
    assert cb.failure_count == 0

    with pytest.raises(RuntimeError):
        async with cb:
            raise RuntimeError("boom")
    assert cb.failure_count == 1


async def test_get_status_reports_state_and_thresholds():
    cb = make_breaker(failure_threshold=4, recovery_timeout=30.0)
    status = cb.get_status()
    assert status["name"] == "test"
    assert status["state"] == "closed"
    assert status["failure_threshold"] == 4
