"""
Regression test for app.services.dialer.ami_action.

panoramisk has no panoramisk.message.Action class - Manager.send_action()
takes a plain dict with an 'Action' key. The dialer used to construct AMI
requests with panoramisk.message.Action(...), which raised AttributeError
on every single AMI call (event subscription, Originate, Hangup, Ping,
CoreShowChannels) - i.e. the dialer could connect to AMI but could never
actually place or manage a call. See app/services/dialer.py:ami_action.
"""

from app.services.dialer import ami_action


def test_ami_action_is_a_plain_dict_with_action_key():
    action = ami_action("Ping")
    assert action == {"Action": "Ping"}


def test_ami_action_merges_extra_params():
    action = ami_action("Originate", {"Channel": "Local/123@dialer_bridge/n", "Async": "true"})
    assert action["Action"] == "Originate"
    assert action["Channel"] == "Local/123@dialer_bridge/n"
    assert action["Async"] == "true"
