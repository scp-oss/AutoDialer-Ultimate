"""
Regression tests for app.services.dialer.ami_action / ami_response_events.

panoramisk has no panoramisk.message.Action class - Manager.send_action()
takes a plain dict with an 'Action' key. The dialer used to construct AMI
requests with panoramisk.message.Action(...), which raised AttributeError
on every single AMI call (event subscription, Originate, Hangup, Ping,
CoreShowChannels) - i.e. the dialer could connect to AMI but could never
actually place or manage a call. See app/services/dialer.py:ami_action.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from panoramisk.message import Message

from app.services.dialer import DialerManager, ami_action, ami_response_events


def test_ami_action_is_a_plain_dict_with_action_key():
    action = ami_action("Ping")
    assert action == {"Action": "Ping"}


def test_ami_action_merges_extra_params():
    action = ami_action("Originate", {"Channel": "Local/123@dialer_bridge/n", "Async": "true"})
    assert action["Action"] == "Originate"
    assert action["Channel"] == "Local/123@dialer_bridge/n"
    assert action["Async"] == "true"


def test_ami_response_events_passes_through_a_list():
    # For "multi" AMI actions (CoreShowChannels etc.) panoramisk's
    # Action.add_message() resolves the future with a plain list of
    # Message objects - confirmed live against a real Asterisk over AMI,
    # where _sync_channels_from_asterisk()/_check_channel_alive() used to
    # do `response.events` and crash every cycle with
    # AttributeError: 'list' object has no attribute 'events'.
    events = [{"event": "CoreShowChannel"}, {"event": "CoreShowChannelsComplete"}]
    assert ami_response_events(events) == events


def test_ami_response_events_wraps_a_single_message():
    # A single-channel query can also resolve to one bare Message (no
    # Start/Complete framing) when Asterisk answers immediately.
    single = {"event": "CoreShowChannel", "channel": "Local/1@dialer_bridge"}
    assert ami_response_events(single) == [single]


class _FakeEventLeader:
    """Stands in for LeaderElection - handle_ami_event() only processes
    events when this worker holds AMI-event-processor leadership (see
    DialerManager._event_leader / _maintain_event_leadership). Defaults to
    True so existing dispatch tests exercise a "we are the leader" worker."""

    def __init__(self, is_leader: bool = True):
        self.is_leader = is_leader


def _bare_manager(is_leader: bool = True) -> DialerManager:
    """A DialerManager with __init__ skipped - just enough state for
    handle_ami_event's dedup cache, without needing a real AMI/DB/Redis
    connection."""
    manager = object.__new__(DialerManager)
    manager.processed_events = {}
    manager._event_leader = _FakeEventLeader(is_leader)
    return manager


@pytest.mark.asyncio
async def test_handle_ami_event_dispatches_on_event_field_not_name():
    # panoramisk.message.Message (a CaseInsensitiveDict) has no real .name
    # attribute - __getattr__ silently falls back to self.get('name', ''),
    # which is always '' since AMI messages carry an "Event:" header (key
    # 'event'), never a 'name' key. handle_ami_event used to read
    # `event_name = event.name`, so this comparison was always against ''
    # and none of the branches below ever matched, for any AMI event, ever.
    # See app/services/dialer.py:handle_ami_event.
    manager = _bare_manager()
    manager._handle_hangup = AsyncMock()
    manager._handle_dial_begin = AsyncMock()
    manager._handle_user_event = AsyncMock()

    hangup = Message.from_line(
        "Event: Hangup\r\nChannel: Local/100@test-1\r\nUniqueid: 123\r\nLinkedid: 123\r\n"
    )
    assert hangup.name == ""  # sanity check documenting the trap in panoramisk
    assert hangup.event == "Hangup"

    await manager.handle_ami_event(manager=None, event=hangup)

    manager._handle_hangup.assert_awaited_once()
    manager._handle_dial_begin.assert_not_awaited()
    manager._handle_user_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_ami_event_deduplicates_by_event_and_uniqueid():
    manager = _bare_manager()
    manager._handle_dial_begin = AsyncMock()

    dial_begin = Message.from_line(
        "Event: DialBegin\r\nChannel: Local/100@dialer_bridge-1\r\nUniqueid: 456\r\n"
    )

    await manager.handle_ami_event(manager=None, event=dial_begin)
    await manager.handle_ami_event(manager=None, event=dial_begin)

    manager._handle_dial_begin.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_ami_event_normalizes_a_duplicated_channel_header_to_a_string():
    # panoramisk.message.Message.from_line stores a header as a LIST
    # instead of a string when the exact same header name appears twice on
    # the raw AMI line - which happened for real once a dialplan
    # UserEvent(...) accidentally included its own "Channel: ..." field
    # alongside Asterisk's native per-event "Channel:" header. Without
    # normalizing, `channel.startswith('Local/')` crashed with
    # AttributeError: 'list' object has no attribute 'startswith' on every
    # single event of that type - confirmed live via a raw AMI capture
    # showing Channel: ['Local/...;2', 'Local/...;2'].
    manager = _bare_manager()
    manager._handle_hangup = AsyncMock()

    hangup = Message.from_line(
        "Event: Hangup\r\nChannel: Local/100@test-1\r\nChannel: Local/100@test-1\r\n"
        "Uniqueid: 321\r\nLinkedid: 321\r\n"
    )
    assert isinstance(hangup.get('channel'), list)  # sanity check on the trap itself

    await manager.handle_ami_event(manager=None, event=hangup)

    manager._handle_hangup.assert_awaited_once()
    awaited_channel = manager._handle_hangup.await_args.args[1]
    assert awaited_channel == "Local/100@test-1"


@pytest.mark.asyncio
async def test_handle_ami_event_skips_processing_on_non_leader_worker():
    # gunicorn runs multiple worker processes, each with its own AMI
    # connection logged in under the same account - Asterisk broadcasts
    # every event to all of them. Without this gate, a single real call
    # used to produce one call_results row per worker (confirmed live: 4
    # duplicate rows under `gunicorn -w 4`). Only the elected leader
    # (_event_leader.is_leader) should actually run the dispatch chain.
    manager = _bare_manager(is_leader=False)
    manager._handle_hangup = AsyncMock()

    hangup = Message.from_line(
        "Event: Hangup\r\nChannel: Local/100@test-1\r\nUniqueid: 789\r\nLinkedid: 789\r\n"
    )

    await manager.handle_ami_event(manager=None, event=hangup)

    manager._handle_hangup.assert_not_awaited()


def test_resolve_action_id_matches_by_channel_prefix_for_a_freshly_dialed_channel():
    # DialBegin/Hangup never carry an ActionID header (confirmed live against
    # real Asterisk - it does not echo the Originate action's ActionID onto
    # events raised by the dialplan's own Dial()). originate_call() used to
    # register nothing useful for a fresh call (`self._add_mapping(action_id,
    # None, None)` - a pure no-op, since both unique_id and channel were
    # None), so _resolve_action_id had no way to ever learn a real call's
    # action_id from its first DialBegin - confirmed live: "DialBegin без
    # ActionID" on every single real call, cascading into "Невозможно
    # разрешить ActionID" CRITICAL on every single Hangup too. Fixed by
    # registering the deterministic channel-name prefix at Originate time
    # (action_to_channel_prefix) and matching it here.
    manager = _bare_manager()
    manager.action_to_channel_prefix = {"call_1_79991234567_1700000000000": "Local/79991234567@dialer_bridge"}
    manager.action_to_channel = {}
    manager.action_to_uniques = {}
    manager.unique_to_action = {}
    manager.channel_map = {}

    action_id = manager._resolve_action_id(
        unique_id="1700000000.5",
        channel="Local/79991234567@dialer_bridge-00000009;2",
    )

    assert action_id == "call_1_79991234567_1700000000000"
    # Resolving also registers the mapping so later events for the same
    # unique_id (BridgeEnter, Hangup, DTMF) resolve via the fast exact-match
    # path without needing the channel prefix again.
    assert manager.unique_to_action["1700000000.5"] == action_id
    assert manager.channel_map["1700000000.5"] == "Local/79991234567@dialer_bridge-00000009;2"


def test_resolve_action_id_does_not_match_an_unrelated_channel_prefix():
    manager = _bare_manager()
    manager.action_to_channel_prefix = {"call_1_79991234567_1700000000000": "Local/79991234567@dialer_bridge"}
    manager.action_to_channel = {}
    manager.unique_to_action = {}
    manager.channel_map = {}

    action_id = manager._resolve_action_id(
        unique_id="1700000000.9",
        channel="Local/79990009999@dialer_bridge-00000011;1",
    )

    assert action_id is None


@pytest.mark.asyncio
async def test_handle_hangup_awaits_force_cleanup_when_action_id_unresolvable():
    # _force_cleanup is an async method but used to be called as
    # `self._force_cleanup(unique_id)` with no await - the coroutine object
    # was created and immediately discarded, so cleanup never actually ran
    # (confirmed live: "RuntimeWarning: coroutine '_force_cleanup' was never
    # awaited" logged on every single unresolvable Hangup).
    manager = _bare_manager()
    manager.hangup_events = {}
    manager.terminated_calls = set()
    manager.redis = AsyncMock()
    manager.redis.set = AsyncMock(return_value=True)
    manager._resolve_action_id = lambda *a, **kw: None
    manager._force_cleanup = AsyncMock()

    hangup = Message.from_line(
        "Event: Hangup\r\nChannel: Local/100@test-1\r\nUniqueid: 999\r\nLinkedid: 999\r\n"
    )

    await manager._handle_hangup(hangup, "Local/100@test-1", "999", "999")

    manager._force_cleanup.assert_awaited_once_with("999")


def _manager_for_start_call() -> DialerManager:
    """A DialerManager with __init__ skipped, wired up with just enough
    mocked state for _start_call() to run its full happy path down to the
    AMI Originate call, without a real DB/Redis/AMI connection."""
    manager = object.__new__(DialerManager)
    manager._init_lua_scripts()

    manager.running = True
    manager.connected = True
    manager.degraded_mode = False
    manager.max_calls = 50
    manager.caller_id = "AutoDialer"
    manager.call_timeout = 30
    manager.active_phones_key = "active_phones"
    manager.active_channels_key = "active_channels"
    manager.active_channels_ts_key = "active_channels_ts"
    manager.call_state_key = "call_states"
    manager.channel_map = {}
    manager.call_contexts = {}
    manager.action_created_at = {}
    manager.action_to_channel_prefix = {}
    manager.local_active_estimate = 0
    manager.last_redis_sync = __import__("time").monotonic()
    manager._local_estimate_lock = __import__("asyncio").Lock()
    manager.adaptive_cps = None
    manager.cps_limiter = MagicMock()
    manager.cps_limiter.try_acquire = AsyncMock(return_value=True)

    def eval_side_effect(script, *args, **kwargs):
        if script is manager.CHECK_PHONE_LUA:
            return [1, "ok"]
        if script is manager.RESERVE_WITH_RESERVATION_LUA:
            return [1, 1]
        if script is manager.TRANSITION_STATE_LUA:
            return 1
        raise AssertionError(f"unexpected Lua script in test: {script!r}")

    manager.redis = AsyncMock()
    manager.redis.eval = AsyncMock(side_effect=eval_side_effect)
    manager.redis.is_system_enabled = AsyncMock(return_value=True)
    manager.redis.scard = AsyncMock(return_value=0)
    manager.redis.setex = AsyncMock()

    manager.manager = AsyncMock()
    manager.manager.send_action = AsyncMock(
        return_value={"response": "Success", "message": "Originate successfully queued"}
    )
    return manager


@pytest.mark.asyncio
async def test_start_call_sends_originate_with_as_list_false():
    # panoramisk's Action.multi property, when as_list is None, treats any
    # response ending in "successfully queued" (which ours does, since we
    # send 'Async': 'true') as the start of a multi-message sequence and
    # keeps the future pending until the eventual OriginateResponse EVENT
    # also arrives - which, for a dialplan-routed Local-channel Originate,
    # only fires once dialplan execution on that channel reaches a
    # completion point. Confirmed live: without as_list=False, a single
    # `await send_action(...)` for Originate took 10.5s to resolve; with
    # it, 0.000s. Since queue_worker() awaits _start_call() directly in
    # its serial loop, every call used to block the entire queue for that
    # long - limiting the whole "auto"dialer to one call at a time.
    manager = _manager_for_start_call()

    await manager._start_call("79991234567", campaign_id=1, retry=0)

    manager.manager.send_action.assert_awaited_once()
    call = manager.manager.send_action.await_args
    assert call.kwargs.get("as_list") is False
    action = call.args[0]
    assert action["Action"] == "Originate"


@pytest.mark.asyncio
async def test_start_call_registers_channel_prefix_before_sending_originate():
    # Registering action_to_channel_prefix AFTER awaiting send_action() is
    # racy: Asterisk can start executing the dialplan and fire DialBegin on
    # the same AMI connection before our own code finishes processing the
    # action's response - confirmed live placing several calls at once,
    # where DialBegin for a freshly originated channel arrived before the
    # registration that was supposed to let it resolve. The mapping must
    # exist before the Originate is even sent, since it depends on nothing
    # but the (already known) normalized phone number and action_id.
    manager = _manager_for_start_call()

    async def send_action_side_effect(*args, **kwargs):
        # At the moment Asterisk would receive this action, the mapping
        # must already be registered.
        assert len(manager.action_to_channel_prefix) == 1
        return {"response": "Success", "message": "Originate successfully queued"}

    manager.manager.send_action = AsyncMock(side_effect=send_action_side_effect)

    await manager._start_call("79991234567", campaign_id=1, retry=0)

    manager.manager.send_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_call_registers_channel_prefix_for_dial_begin_resolution():
    # originate_call() used to do `self._add_mapping(action_id, None, None)`
    # on a successful Originate - a pure no-op, since both unique_id and
    # channel were None. DialBegin/Hangup never carry an ActionID header
    # (confirmed live against real Asterisk), so this was the only
    # opportunity to ever let _resolve_action_id learn a real call's
    # action_id - meaning DialBegin ("DialBegin без ActionID") and,
    # cascading from that, Hangup ("Невозможно разрешить ActionID")
    # resolution failed for every single real call ever placed.
    manager = _manager_for_start_call()

    await manager._start_call("79991234567", campaign_id=1, retry=0)

    assert len(manager.action_to_channel_prefix) == 1
    action_id, prefix = next(iter(manager.action_to_channel_prefix.items()))
    assert prefix == "Local/79991234567@dialer_bridge"
    assert action_id.startswith("call_1_79991234567_")


@pytest.mark.asyncio
async def test_queue_worker_does_not_pop_the_dial_queue_on_a_non_leader_worker():
    # action_to_channel_prefix/channel_map/call_contexts are all in-process
    # memory, not shared across gunicorn workers. handle_ami_event only
    # processes events on the current leader (_event_leader), so if a
    # non-leader worker's queue_worker() places the call, the leader
    # receives DialBegin/Hangup for a channel its own memory has never
    # heard of - resolution is guaranteed to fail. Confirmed live: most
    # calls logged "DialBegin без ActionID" (or, worse, a resolved but
    # WRONG action_id via a stale prefix match from an older call), except
    # the rare case where BLPOP happened to land on the leader itself.
    # Consolidating call placement onto the leader closes that gap.
    manager = _bare_manager(is_leader=False)
    manager.running = True
    manager.redis = AsyncMock()
    manager.redis.blpop = AsyncMock(return_value=None)
    manager._start_call = AsyncMock()

    call_count = 0

    async def fake_sleep(_seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            manager.running = False

    with patch("app.services.dialer.asyncio.sleep", side_effect=fake_sleep):
        await manager.queue_worker()

    manager.redis.blpop.assert_not_awaited()
    manager._start_call.assert_not_awaited()
