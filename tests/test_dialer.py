"""
Regression tests for app.services.dialer.ami_action / ami_response_events.

panoramisk has no panoramisk.message.Action class - Manager.send_action()
takes a plain dict with an 'Action' key. The dialer used to construct AMI
requests with panoramisk.message.Action(...), which raised AttributeError
on every single AMI call (event subscription, Originate, Hangup, Ping,
CoreShowChannels) - i.e. the dialer could connect to AMI but could never
actually place or manage a call. See app/services/dialer.py:ami_action.
"""

from unittest.mock import AsyncMock

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
