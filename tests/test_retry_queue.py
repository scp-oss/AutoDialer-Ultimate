"""
Regression test for app.workers.retry.process_retry_queue's UPDATE
statement.

campaign_contacts has no updated_at column (only created_at, see
sql/schema.sql) - `SET next_retry_at = NULL, updated_at = NOW()` crashed
with `column "updated_at" of relation "campaign_contacts" does not
exist` on every single retry attempt, confirmed live: the retry queue
never processed a single contact in the project's history.

This environment's local Postgres isn't wired up for the existing
DB-backed pytest fixtures (see tests/test_contacts_upsert.py for the same
situation), so this is a static source check rather than a live query
test.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_process_retry_queue_does_not_reference_nonexistent_updated_at_column():
    content = (REPO_ROOT / "app" / "workers" / "retry.py").read_text()
    update_start = content.index("UPDATE campaign_contacts")
    update_statement = content[update_start:content.index('"""', update_start)]
    assert "updated_at" not in update_statement, (
        "campaign_contacts has no updated_at column (see sql/schema.sql) - "
        "referencing it in the retry-queue UPDATE crashes every retry attempt"
    )
