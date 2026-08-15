"""
Regression tests for asterisk/extensions.conf.

These bugs were only found by actually running the full stack (Docker
compose: postgres/redis/asterisk/backend) and originating a real call
through the dialer_bridge context, then tracing the raw AMI UserEvent
Asterisk sent versus what app.services.dialer received. Static analysis
of the dialplan text alone would not have caught them - they are pure
Asterisk-semantics bugs, not Python bugs - so they are pinned here as
plain-text regression checks against the shipped dialplan file.
"""

from pathlib import Path

EXTENSIONS_CONF = Path(__file__).resolve().parent.parent / "asterisk" / "extensions.conf"


def _read() -> str:
    return EXTENSIONS_CONF.read_text()


def test_userevent_bodies_use_colon_not_equals_for_key_value_pairs():
    # Per `asterisk -rx "core show application UserEvent"`: "The <body> may
    # be specified as a ',' delimited list of key:value pairs." Asterisk's
    # app_userevent.c writes each comma-separated argument verbatim as one
    # AMI header line - it does NOT split on '='. So
    # UserEvent(DialerResult,Status=busy,Campaign=${CAMPAIGN_ID},...)
    # produced header lines like "Status=busy" with no colon, which is not
    # a valid "Header: Value" AMI line and panoramisk silently drops it -
    # meaning Status/Campaign/Phone/RetryCount/DTMF/Duration/BillSec were
    # NEVER present on the Python side of any DialerResult/DialerHangup
    # event, ever. Confirmed live: switching to "Key: Value" made the
    # fields actually appear on the parsed AMI event.
    # Dialplan lines are single-line, so match "UserEvent(" through the
    # line's closing paren rather than a naive `[^)]*` group - the body
    # itself legitimately contains nested parens, e.g. ${CHANNEL(linkedid)}.
    userevent_lines = [
        line
        for line in _read().splitlines()
        if "UserEvent(" in line and not line.strip().startswith(";")
    ]
    assert userevent_lines, "expected at least one UserEvent(...) dialplan line"

    for line in userevent_lines:
        start = line.index("UserEvent(") + len("UserEvent(")
        body = line[start : line.rindex(")")]
        # First segment is the event name (DialerResult/DialerHangup); the
        # rest must each be "Key: value", never "Key=value".
        segments = body.split(",")[1:]
        for segment in segments:
            assert ":" in segment, (
                f"UserEvent body segment {segment!r} must use 'Key: value' "
                f"(colon), not 'Key=value' - Asterisk emits it as a raw AMI "
                f"header line, and '=' is not a valid AMI header separator"
            )
            key = segment.split(":", 1)[0]
            assert "=" not in key, (
                f"UserEvent body segment {segment!r} has '=' before the "
                f"colon in its key ({key!r})"
            )


def test_original_phone_is_set_as_an_inheritable_variable():
    # [sub-media] runs on the channel Dial() spawns (via the U() Gosub
    # option), not on the dialer_bridge channel that calls Dial(). Asterisk
    # only propagates "_"/"__"-prefixed (inheritable) variables to that
    # spawned channel. ORIGINAL_PHONE used to be set with no prefix, so
    # every UserEvent(DialerResult,...Phone: ${ORIGINAL_PHONE}...) emitted
    # by [sub-media] carried an empty Phone field for every real call ever
    # placed. Confirmed live: after switching to __ORIGINAL_PHONE, the
    # phone number correctly appeared in the persisted call_results row.
    content = _read()
    assert "Set(__ORIGINAL_PHONE=${EXTEN})" in content
    assert "Set(ORIGINAL_PHONE=${EXTEN})" not in content
