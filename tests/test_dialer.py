"""
Regression tests for app.services.dialer.ami_action / ami_response_events.

panoramisk has no panoramisk.message.Action class - Manager.send_action()
takes a plain dict with an 'Action' key. The dialer used to construct AMI
requests with panoramisk.message.Action(...), which raised AttributeError
on every single AMI call (event subscription, Originate, Hangup, Ping,
CoreShowChannels) - i.e. the dialer could connect to AMI but could never
actually place or manage a call. See app/services/dialer.py:ami_action.
"""

from app.services.dialer import ami_action, ami_response_events


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
