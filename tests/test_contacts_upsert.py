"""
Regression tests pinning the contacts-upsert SQL against a race condition
and a partial-index mismatch found by placing real concurrent calls to the
same phone number through the live stack.

sql/schema.sql defines the only unique constraint on contacts.phone as a
PARTIAL index: `idx_contacts_phone_active ON contacts(phone) WHERE NOT
blacklisted`. Postgres only accepts a partial index as an ON CONFLICT
arbiter if the ON CONFLICT clause's predicate matches it exactly - and
only reads live DB state at query time, so these bugs are not reachable
from a mocked unit test. Pinned here as plain-text checks against the
shipped source, the same technique tests/test_dialplan.py already uses for
a similar (dialplan, not SQL) class of bug.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_call_result_service_upserts_contacts_atomically():
    # save_call_result() used to do `SELECT id FROM contacts WHERE phone =
    # $1` and, if nothing came back, a separate INSERT with no conflict
    # handling at all. dialer_bridge executes twice per call (once per
    # half of the Local channel, due to the /n flag), so two
    # UserEvent(DialerResult) for the same phone can arrive and get saved
    # within milliseconds of each other - both see "no contact", both
    # INSERT, the second fails with:
    # duplicate key value violates unique constraint
    # "idx_contacts_phone_active"
    # Confirmed live placing a real call through the actual dial queue.
    content = (REPO_ROOT / "app" / "services" / "call_result.py").read_text()
    assert "SELECT id FROM contacts WHERE phone" not in content, (
        "save_call_result() must not use a separate SELECT-then-INSERT for "
        "contacts - it races when two results for the same phone save "
        "close together. Use a single atomic INSERT ... ON CONFLICT."
    )
    assert "ON CONFLICT (phone) WHERE NOT blacklisted" in content, (
        "the contacts upsert must match idx_contacts_phone_active's exact "
        "partial predicate (WHERE NOT blacklisted), or Postgres won't "
        "accept it as an ON CONFLICT arbiter at all"
    )


def test_dialer_fallback_contact_upsert_matches_the_partial_index():
    # DialerManager._save_call_result()'s fallback path (used when
    # call_result_service is None) did `ON CONFLICT (phone) DO UPDATE ...`
    # with no predicate - idx_contacts_phone_active is a PARTIAL unique
    # index (`WHERE NOT blacklisted`), and Postgres requires the ON
    # CONFLICT predicate to match a partial index's predicate exactly to
    # accept it as a conflict arbiter. Without it, Postgres rejects the
    # query outright: "there is no unique or exclusion constraint matching
    # the ON CONFLICT specification" - on every single conflict.
    content = (REPO_ROOT / "app" / "services" / "dialer.py").read_text()
    assert "ON CONFLICT (phone) WHERE NOT blacklisted" in content, (
        "the fallback contacts upsert in _save_call_result() must match "
        "idx_contacts_phone_active's exact partial predicate"
    )
