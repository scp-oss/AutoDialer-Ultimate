"""Fix contacts/contact_groups schema drift

sql/schema.sql's `contacts` table was missing phone2, phone3, gender,
birth_date, company, position, country, region, city, address,
postal_code, source, last_call_status, successful_calls, dnd, dnd_until,
view_count, deleted_at - all fields app/services/contact.py's
ContactService has always read/written. `contact_groups` was missing
is_public/updated_at. Three tables the service reads/writes directly
(contact_group_members, contact_tags, contact_notes_history) never
existed at all, causing UndefinedTableError on every group-membership,
tag, or notes-history operation.

Found via the same static INSERT-column-vs-schema diff used for
`blacklist` (see 0002/ROADMAP §3.0), confirmed live: create_contact()
failed on `phone2` before this fix, and the full ContactService/
ContactGroupService flow (create/get/update/list/blacklist/delete/
restore/export/bulk-import + groups) was smoke-tested end to end after.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE contact_groups
            ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)

    op.execute("""
        ALTER TABLE contacts
            ADD COLUMN IF NOT EXISTS phone2 VARCHAR(20),
            ADD COLUMN IF NOT EXISTS phone3 VARCHAR(20),
            ADD COLUMN IF NOT EXISTS gender VARCHAR(10) DEFAULT 'unknown',
            ADD COLUMN IF NOT EXISTS birth_date DATE,
            ADD COLUMN IF NOT EXISTS company VARCHAR(255),
            ADD COLUMN IF NOT EXISTS position VARCHAR(255),
            ADD COLUMN IF NOT EXISTS country VARCHAR(100),
            ADD COLUMN IF NOT EXISTS region VARCHAR(100),
            ADD COLUMN IF NOT EXISTS city VARCHAR(100),
            ADD COLUMN IF NOT EXISTS address TEXT,
            ADD COLUMN IF NOT EXISTS postal_code VARCHAR(20),
            ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual',
            ADD COLUMN IF NOT EXISTS last_call_status VARCHAR(50),
            ADD COLUMN IF NOT EXISTS successful_calls INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS dnd BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS dnd_until TIMESTAMP,
            ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP
    """)

    # Widen the status CHECK to include 'blacklisted'/'error' (ContactStatus
    # enum) - Postgres has no ADD COLUMN IF NOT EXISTS equivalent for CHECK,
    # so drop-and-recreate by name (matches the constraint schema.sql's
    # inline CHECK on this column would generate).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'contacts_status_check'
            ) THEN
                ALTER TABLE contacts DROP CONSTRAINT contacts_status_check;
            END IF;
            ALTER TABLE contacts ADD CONSTRAINT contacts_status_check
                CHECK (status IN ('active', 'inactive', 'blocked', 'blacklisted', 'error'));
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS contact_group_members (
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            group_id INTEGER NOT NULL REFERENCES contact_groups(id) ON DELETE CASCADE,
            is_primary BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (contact_id, group_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS contact_tags (
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (contact_id, tag)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS contact_notes_history (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_contacts_deleted_at ON contacts(deleted_at) WHERE deleted_at IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contact_group_members_group ON contact_group_members(group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contact_tags_contact ON contact_tags(contact_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contact_notes_history_contact ON contact_notes_history(contact_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contact_notes_history")
    op.execute("DROP TABLE IF EXISTS contact_tags")
    op.execute("DROP TABLE IF EXISTS contact_group_members")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'contacts_status_check'
            ) THEN
                ALTER TABLE contacts DROP CONSTRAINT contacts_status_check;
            END IF;
            ALTER TABLE contacts ADD CONSTRAINT contacts_status_check
                CHECK (status IN ('active', 'inactive', 'blocked'));
        END $$;
    """)
    op.execute("""
        ALTER TABLE contacts
            DROP COLUMN IF EXISTS phone2,
            DROP COLUMN IF EXISTS phone3,
            DROP COLUMN IF EXISTS gender,
            DROP COLUMN IF EXISTS birth_date,
            DROP COLUMN IF EXISTS company,
            DROP COLUMN IF EXISTS position,
            DROP COLUMN IF EXISTS country,
            DROP COLUMN IF EXISTS region,
            DROP COLUMN IF EXISTS city,
            DROP COLUMN IF EXISTS address,
            DROP COLUMN IF EXISTS postal_code,
            DROP COLUMN IF EXISTS source,
            DROP COLUMN IF EXISTS last_call_status,
            DROP COLUMN IF EXISTS successful_calls,
            DROP COLUMN IF EXISTS dnd,
            DROP COLUMN IF EXISTS dnd_until,
            DROP COLUMN IF EXISTS view_count,
            DROP COLUMN IF EXISTS deleted_at
    """)
    op.execute("""
        ALTER TABLE contact_groups
            DROP COLUMN IF EXISTS is_public,
            DROP COLUMN IF EXISTS updated_at
    """)
