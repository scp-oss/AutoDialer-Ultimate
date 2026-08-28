"""
Concurrency check: does the real handle_ami_event()/_handle_user_event()
code path correctly attribute results to the right phone number when many
calls are in flight at once, instead of some shared/global state mixing
them up?

Runs 10 simulated calls (mixed campaigns, mixed outcomes, including a
duplicate DialerResult per call to mimic the real "two Local-channel
halves" architecture) through the ACTUAL dialer.py functions concurrently
via asyncio.gather - the same single-event-loop concurrency model the real
leader worker uses for AMI events - and asserts every phone ends up with
exactly its own intended status, no cross-contamination, no dropped or
duplicated rows.

No real Asterisk/DB/Redis involved - db_pool and redis are minimal fakes
that record what was written, but the resolution/dedup/save logic being
exercised is the real code from app/services/dialer.py, not a reimplementation.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from panoramisk.message import Message

from app.services.dialer import DialerManager, CallContext


class _FakeEventLeader:
    def __init__(self, is_leader: bool = True):
        self.is_leader = is_leader


class _FakeRedis:
    """Just enough of redis.asyncio's API for _handle_user_event's
    dedup: SET key val EX 300 NX - real semantics (atomic, returns
    falsy if the key already existed)."""

    def __init__(self):
        self._keys = set()
        self._lock = asyncio.Lock()

    async def set(self, key, value, ex=None, nx=False):
        async with self._lock:
            if nx and key in self._keys:
                return None
            self._keys.add(key)
            return True


class _FakeConn:
    def __init__(self, store):
        self.store = store

    async def fetchval(self, query, *args):
        if "INSERT INTO contacts" in query:
            phone = args[0]
            self.store["contacts"].setdefault(phone, len(self.store["contacts"]) + 1)
            return self.store["contacts"][phone]
        raise AssertionError(f"unexpected fetchval in test: {query}")

    async def execute(self, query, *args):
        if "INSERT INTO call_results" in query:
            # (campaign_id, contact_id, linked_id, unique_id, status, retry, duration)
            self.store["results"].append(args)
            return
        raise AssertionError(f"unexpected execute in test: {query}")


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, store):
        self.store = store

    def acquire(self):
        return _FakeAcquire(_FakeConn(self.store))


def _bare_manager():
    """DialerManager with __init__ skipped, wired up with fake db_pool/redis
    but otherwise using the manager's real methods (_resolve_action_id,
    _handle_user_event, _save_call_result, normalize_phone, ...)."""
    manager = object.__new__(DialerManager)
    manager.processed_events = {}
    manager._event_leader = _FakeEventLeader(True)
    manager.unique_to_action = {}
    manager.channel_map = {}
    manager.action_to_channel = {}
    manager.action_to_uniques = {}
    manager.call_contexts = {}
    manager.call_result_service = None  # exercise the direct-DB fallback path
    manager._schedule_retry = AsyncMock()  # retry scheduling is a separate concern

    store = {"contacts": {}, "results": []}
    manager.db_pool = _FakePool(store)
    manager.redis = _FakeRedis()
    return manager, store


def _dialer_result_event(*, status, campaign_id, phone, linked_id, pjsip_unique_id, duration, retry_count=0):
    lines = (
        "Event: UserEvent\r\n"
        "UserEvent: DialerResult\r\n"
        f"Status: {status}\r\n"
        f"Campaign: {campaign_id}\r\n"
        f"Phone: {phone}\r\n"
        f"RetryCount: {retry_count}\r\n"
        f"LinkedID: {linked_id}\r\n"
        f"Duration: {duration}\r\n"
        f"Uniqueid: {pjsip_unique_id}\r\n"
        f"Channel: PJSIP/291_endpoint-{pjsip_unique_id}\r\n"
    )
    return Message.from_line(lines)


@pytest.mark.asyncio
async def test_ten_concurrent_calls_do_not_cross_attribute_results():
    manager, store = _bare_manager()

    calls = [
        {"phone": "79990000001", "campaign_id": 1, "status": "agreed"},
        {"phone": "79990000002", "campaign_id": 1, "status": "declined"},
        {"phone": "79990000003", "campaign_id": 1, "status": "timeout"},
        {"phone": "79990000004", "campaign_id": 1, "status": "machine"},
        {"phone": "79990000005", "campaign_id": 1, "status": "announced"},
        {"phone": "79990000006", "campaign_id": 2, "status": "agreed"},
        {"phone": "79990000007", "campaign_id": 2, "status": "busy"},
        {"phone": "79990000008", "campaign_id": 2, "status": "noanswer"},
        {"phone": "79990000009", "campaign_id": 2, "status": "declined"},
        {"phone": "79990000010", "campaign_id": 2, "status": "agreed"},
    ]

    # Simulate DialBegin having already run for each call: action_id
    # registered, linked_id -> action_id mapping in place, CallContext
    # holding the real phone/campaign for that call - exactly the state
    # _handle_dial_begin leaves behind in the real flow.
    for i, call in enumerate(calls):
        action_id = f"call_{call['campaign_id']}_{call['phone']}_{i}"
        linked_id = f"17879{i:06d}.100"
        call["action_id"] = action_id
        call["linked_id"] = linked_id
        call["pjsip_unique_id"] = f"17879{i:06d}.200"

        manager.unique_to_action[linked_id] = action_id
        manager.call_contexts[action_id] = CallContext(
            action_id=action_id,
            campaign_id=call["campaign_id"],
            phone=call["phone"],
        )

    # Fire every call's DialerResult TWICE (mimicking the real duplicate-
    # Local-channel-half architecture sending the same result twice) and
    # interleave all 20 events concurrently via asyncio.gather - the same
    # single-event-loop concurrency the real leader worker uses.
    tasks = []
    for i, call in enumerate(calls):
        for attempt in range(2):
            event = _dialer_result_event(
                status=call["status"],
                campaign_id=call["campaign_id"],
                phone=call["phone"],
                linked_id=call["linked_id"],
                pjsip_unique_id=call["pjsip_unique_id"],
                duration=10 + i,
            )
            tasks.append(manager.handle_ami_event(manager=None, event=event))

    await asyncio.gather(*tasks)

    # Exactly one saved row per call - the duplicate must be suppressed,
    # not silently dropped AND not double-counted.
    assert len(store["results"]) == len(calls), (
        f"expected {len(calls)} saved call_results, got {len(store['results'])}: "
        f"{store['results']}"
    )

    contact_id_to_phone = {v: k for k, v in store["contacts"].items()}

    for call in calls:
        contact_id = store["contacts"][call["phone"]]
        matching = [r for r in store["results"] if r[1] == contact_id]
        assert len(matching) == 1, (
            f"phone {call['phone']} has {len(matching)} rows, expected 1: {matching}"
        )
        row = matching[0]
        campaign_id, _contact_id, linked_id, _unique_id, status, _retry, _duration = row
        assert campaign_id == call["campaign_id"], (
            f"phone {call['phone']}: expected campaign {call['campaign_id']}, "
            f"got {campaign_id} (cross-attribution!)"
        )
        assert status == call["status"], (
            f"phone {call['phone']}: expected status {call['status']}, got {status} "
            f"(cross-attribution!)"
        )
        assert linked_id == call["linked_id"], (
            f"phone {call['phone']}: saved linked_id {linked_id} doesn't match "
            f"this call's own {call['linked_id']} (cross-attribution!)"
        )

    # No phone accidentally shares a contact_id with another (would itself
    # indicate normalize_phone/contact resolution mixing calls up).
    assert len(contact_id_to_phone) == len(calls)
