"""
Unit tests for app.utils.rate_limiter.TokenBucket - the local, in-memory
CPS limiter that gates outbound call rate in DialerManager._start_call()
(app/services/dialer.py) and CampaignService.dial_task() (app/services/
campaign.py: `TokenBucket(campaign['cps'])`). Pure asyncio, no Redis - safe
to test directly. asyncio_mode = "auto" (pyproject.toml).
"""

import asyncio

import pytest

from app.utils.rate_limiter import TokenBucket


async def test_starts_at_full_capacity():
    bucket = TokenBucket(rate=10.0)
    assert bucket.get_available_tokens() == 10.0


async def test_capacity_defaults_to_rate():
    bucket = TokenBucket(rate=5.0)
    assert bucket.capacity == 5.0


async def test_capacity_can_be_overridden():
    bucket = TokenBucket(rate=5.0, capacity=20.0)
    assert bucket.capacity == 20.0
    assert bucket.get_available_tokens() == 20.0


async def test_try_acquire_consumes_tokens():
    bucket = TokenBucket(rate=10.0, capacity=10.0)
    assert await bucket.try_acquire(1.0) is True
    assert bucket.get_available_tokens() == pytest.approx(9.0, abs=0.05)


async def test_try_acquire_fails_when_empty_without_waiting():
    bucket = TokenBucket(rate=1.0, capacity=1.0)
    assert await bucket.try_acquire(1.0) is True
    assert await bucket.try_acquire(1.0) is False


async def test_refill_replenishes_tokens_over_time():
    bucket = TokenBucket(rate=10.0, capacity=10.0)
    await bucket.try_acquire(10.0)
    assert bucket.get_available_tokens() < 1.0

    await asyncio.sleep(0.2)  # ~10 tokens/s * 0.2s ~= 2 tokens

    available = bucket.get_available_tokens()
    assert 1.0 <= available <= 3.0


async def test_refill_never_exceeds_capacity():
    bucket = TokenBucket(rate=100.0, capacity=5.0)
    await asyncio.sleep(0.1)  # would refill ~10 tokens without the cap
    assert bucket.get_available_tokens() == 5.0


async def test_acquire_more_than_capacity_raises_value_error():
    bucket = TokenBucket(rate=5.0, capacity=5.0)
    with pytest.raises(ValueError):
        await bucket.acquire(10.0)


async def test_acquire_waits_for_missing_tokens():
    bucket = TokenBucket(rate=100.0, capacity=1.0)
    await bucket.try_acquire(1.0)  # drain the single token

    loop = asyncio.get_event_loop()
    start = loop.time()
    assert await bucket.acquire(1.0) is True
    elapsed = loop.time() - start
    # 1 token at 100/s should take ~0.01s, not return instantly
    assert elapsed > 0.0


async def test_reset_restores_full_capacity():
    bucket = TokenBucket(rate=5.0, capacity=5.0)
    await bucket.try_acquire(5.0)
    assert bucket.get_available_tokens() < 1.0

    bucket.reset()
    assert bucket.get_available_tokens() == 5.0


async def test_update_rate_changes_refill_speed():
    bucket = TokenBucket(rate=1.0, capacity=10.0)
    await bucket.try_acquire(10.0)  # drain fully

    bucket.update_rate(1000.0)
    await asyncio.sleep(0.05)

    # At the original rate=1.0/s, 0.05s would refill ~0.05 tokens.
    # At the updated rate, it should be well past 1 token.
    assert bucket.get_available_tokens() > 1.0


async def test_get_stats_tracks_acquired_and_rejected():
    bucket = TokenBucket(rate=1.0, capacity=1.0)
    await bucket.try_acquire(1.0)  # acquired
    await bucket.try_acquire(1.0)  # rejected, bucket empty

    stats = bucket.get_stats()
    assert stats["acquired"] == 1
    assert stats["rejected"] == 1
