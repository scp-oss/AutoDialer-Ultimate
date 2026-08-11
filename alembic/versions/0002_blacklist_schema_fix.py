"""Fix blacklist table schema drift

sql/schema.sql's `blacklist` table only ever had 5 columns (id, phone,
reason, created_by, created_at), while app/services/blacklist.py (a
~1100-line, actively used service - soft-delete status, expiry, tags,
CSV export, bulk operations) has always assumed a much richer table:
status, reason_details, expires_at, source, notes, updated_at, removed_at,
removed_by, removed_reason, times_called_before, plus two tables the
service reads/writes directly (blacklist_tags, blacklist_history) that
never existed at all. Every blacklist operation (add/remove/check/list/
export) failed with asyncpg.exceptions.UndefinedColumnError /
UndefinedTableError against a DB built from schema.sql - this was only
caught by testing the service against a real database while writing
tests/test_blacklist_service.py's mocks (which don't validate column
names) and then a real add/check/list/export smoke run.

This migration brings an already-deployed 0001 database in line with the
now-corrected sql/schema.sql so both deployment paths (fresh Alembic
`upgrade head` and this incremental step) converge on the same schema.
Also tightens check_blacklist() to only mark a contact blacklisted for an
*active* blacklist entry - previously any row for that phone (even a
soft-removed one) satisfied the trigger's EXISTS check.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE blacklist
            ADD COLUMN IF NOT EXISTS reason_details TEXT,
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual',
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS times_called_before INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS removed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS removed_reason TEXT
    """)
    op.execute("UPDATE blacklist SET status = 'active' WHERE status IS NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS blacklist_tags (
            blacklist_id INTEGER NOT NULL REFERENCES blacklist(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (blacklist_id, tag)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS blacklist_history (
            id SERIAL PRIMARY KEY,
            blacklist_id INTEGER NOT NULL REFERENCES blacklist(id) ON DELETE CASCADE,
            action VARCHAR(50) NOT NULL,
            details JSONB DEFAULT '{}',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_status ON blacklist(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_tags_blacklist_id ON blacklist_tags(blacklist_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_history_blacklist_id ON blacklist_history(blacklist_id)")

    op.execute("""
        CREATE OR REPLACE FUNCTION check_blacklist()
        RETURNS TRIGGER AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM blacklist WHERE phone = NEW.phone AND status = 'active') THEN
                NEW.blacklisted = TRUE;
                NEW.blacklist_reason = COALESCE(NEW.blacklist_reason, 'Number in blacklist');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION check_blacklist()
        RETURNS TRIGGER AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM blacklist WHERE phone = NEW.phone) THEN
                NEW.blacklisted = TRUE;
                NEW.blacklist_reason = COALESCE(NEW.blacklist_reason, 'Number in blacklist');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TABLE IF EXISTS blacklist_history")
    op.execute("DROP TABLE IF EXISTS blacklist_tags")
    op.execute("""
        ALTER TABLE blacklist
            DROP COLUMN IF EXISTS reason_details,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS expires_at,
            DROP COLUMN IF EXISTS source,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS times_called_before,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS removed_at,
            DROP COLUMN IF EXISTS removed_by,
            DROP COLUMN IF EXISTS removed_reason
    """)
