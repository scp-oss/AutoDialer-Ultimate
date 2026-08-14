"""Fix incoming_calls/incoming_call_tags/incoming_call_events schema drift

sql/schema.sql's `incoming_calls` table was missing caller_name,
called_number, recording_format, unique_id, linked_id, language, status,
contact_id, transcription_engine, transcription_error,
transcription_segments, listened_at, listened_by, created_at, updated_at -
all read/written by app/services/incoming.py's IncomingCallService
(process_webhook's INSERT, _transcribe_call/start_transcription's UPDATEs,
mark_listened, update_incoming_call, _find_or_create_contact's linkage,
get_incoming_call/list_incoming_calls SELECTs). Every incoming-call
webhook would fail with UndefinedColumnError on INSERT.
`incoming_call_tags` table did not exist at all - every
_get_call_tags()/_update_call_tags() call would fail with
UndefinedTableError. `incoming_call_events` did not exist either -
_get_listen_history()/delete_incoming_call() read/delete from it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE incoming_calls
            ADD COLUMN IF NOT EXISTS caller_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS called_number VARCHAR(20),
            ADD COLUMN IF NOT EXISTS recording_format VARCHAR(10) DEFAULT 'wav',
            ADD COLUMN IF NOT EXISTS unique_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS linked_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'ru',
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'new',
            ADD COLUMN IF NOT EXISTS contact_id INTEGER,
            ADD COLUMN IF NOT EXISTS transcription_engine VARCHAR(20),
            ADD COLUMN IF NOT EXISTS transcription_error TEXT,
            ADD COLUMN IF NOT EXISTS transcription_segments JSONB,
            ADD COLUMN IF NOT EXISTS listened_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS listened_by INTEGER,
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'incoming_calls_contact_id_fkey'
            ) THEN
                ALTER TABLE incoming_calls ADD CONSTRAINT incoming_calls_contact_id_fkey
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'incoming_calls_listened_by_fkey'
            ) THEN
                ALTER TABLE incoming_calls ADD CONSTRAINT incoming_calls_listened_by_fkey
                    FOREIGN KEY (listened_by) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'incoming_calls_unique_id_key'
            ) THEN
                ALTER TABLE incoming_calls ADD CONSTRAINT incoming_calls_unique_id_key UNIQUE (unique_id);
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'incoming_calls_status_check'
            ) THEN
                ALTER TABLE incoming_calls DROP CONSTRAINT incoming_calls_status_check;
            END IF;
            ALTER TABLE incoming_calls ADD CONSTRAINT incoming_calls_status_check
                CHECK (status IN ('new', 'listened', 'archived', 'deleted'));
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS incoming_call_tags (
            incoming_call_id INTEGER NOT NULL REFERENCES incoming_calls(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (incoming_call_id, tag)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS incoming_call_events (
            id SERIAL PRIMARY KEY,
            incoming_call_id INTEGER NOT NULL REFERENCES incoming_calls(id) ON DELETE CASCADE,
            event_type VARCHAR(50) NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            details JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_incoming_calls_call_status ON incoming_calls(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_incoming_calls_contact ON incoming_calls(contact_id) WHERE contact_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_incoming_calls_called_number ON incoming_calls(called_number)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_incoming_call_tags_call ON incoming_call_tags(incoming_call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_incoming_call_events_call ON incoming_call_events(incoming_call_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incoming_call_events")
    op.execute("DROP TABLE IF EXISTS incoming_call_tags")
    op.execute("""
        ALTER TABLE incoming_calls
            DROP CONSTRAINT IF EXISTS incoming_calls_status_check,
            DROP CONSTRAINT IF EXISTS incoming_calls_unique_id_key,
            DROP CONSTRAINT IF EXISTS incoming_calls_listened_by_fkey,
            DROP CONSTRAINT IF EXISTS incoming_calls_contact_id_fkey,
            DROP COLUMN IF EXISTS caller_name,
            DROP COLUMN IF EXISTS called_number,
            DROP COLUMN IF EXISTS recording_format,
            DROP COLUMN IF EXISTS unique_id,
            DROP COLUMN IF EXISTS linked_id,
            DROP COLUMN IF EXISTS language,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS contact_id,
            DROP COLUMN IF EXISTS transcription_engine,
            DROP COLUMN IF EXISTS transcription_error,
            DROP COLUMN IF EXISTS transcription_segments,
            DROP COLUMN IF EXISTS listened_at,
            DROP COLUMN IF EXISTS listened_by,
            DROP COLUMN IF EXISTS created_at,
            DROP COLUMN IF EXISTS updated_at
    """)
