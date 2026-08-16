"""
Regression test for IncomingCallService.get_incoming_call()'s
listened_by_name field.

get_incoming_call() used to hardcode `listened_by_name=None` with a
"TODO: join users" comment - the field existed on the response model and
was documented in its own example ("admin"), but never actually
populated. Verified live: inserted a real incoming_calls row with
listened_by set to the admin user, and GET /api/incoming-calls/{id}
returned listened_by_name: null until the query below was added.

This environment's local Postgres isn't wired up for the existing
DB-backed pytest fixtures (see tests/test_contacts_upsert.py for the same
situation), so this is a static source check rather than a live query
test - the live verification is documented in ROADMAP.md.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_get_incoming_call_joins_users_for_listened_by_name():
    content = (REPO_ROOT / "app" / "services" / "incoming.py").read_text()
    assert "listened_by_name=None" not in content, (
        "get_incoming_call() must not hardcode listened_by_name=None - "
        "it should come from a JOIN against users.listened_by"
    )
    assert "LEFT JOIN users u ON ic.listened_by = u.id" in content
    assert "listened_by_name=row['listened_by_name']" in content
