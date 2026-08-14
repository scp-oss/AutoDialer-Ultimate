"""Fix audio_files/audio_tags/audio_usage schema drift

sql/schema.sql's `audio_files` table was missing file_name, status,
sample_rate, channels, bitrate, converted_from_id, tts_text, tts_voice,
tts_model, tts_speed, updated_at, view_count, usage_count, last_used_at,
deleted_at - all read/written by app/services/audio.py's
AudioService/TTSService (upload_audio, convert_audio, generate_audio,
get_audio's view_count increment, get_audio_file_path's usage_count/
last_used_at). `audio_tags` and `audio_usage` tables never existed at
all - every _add_audio_tags()/_get_audio_tags()/_get_usage_history()
call would fail with UndefinedTableError.

Also fixes a real type-mismatch bug: `duration` was declared INTEGER,
but AudioMetadata.duration/AudioResponse.duration are floats (soxi -D
returns fractional seconds, e.g. 15.5) - inserting a non-integer
duration into an INTEGER column fails with an asyncpg DataError on
essentially every upload/TTS generation. Widened to DOUBLE PRECISION.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audio_files
            ADD COLUMN IF NOT EXISTS file_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'ready',
            ADD COLUMN IF NOT EXISTS sample_rate INTEGER,
            ADD COLUMN IF NOT EXISTS channels INTEGER,
            ADD COLUMN IF NOT EXISTS bitrate INTEGER,
            ADD COLUMN IF NOT EXISTS converted_from_id INTEGER,
            ADD COLUMN IF NOT EXISTS tts_text TEXT,
            ADD COLUMN IF NOT EXISTS tts_voice VARCHAR(20),
            ADD COLUMN IF NOT EXISTS tts_model VARCHAR(20),
            ADD COLUMN IF NOT EXISTS tts_speed REAL,
            ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP
    """)
    op.execute("ALTER TABLE audio_files ALTER COLUMN duration TYPE DOUBLE PRECISION")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'audio_files_converted_from_id_fkey'
            ) THEN
                NULL;
            ELSE
                ALTER TABLE audio_files ADD CONSTRAINT audio_files_converted_from_id_fkey
                    FOREIGN KEY (converted_from_id) REFERENCES audio_files(id) ON DELETE SET NULL;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'audio_files_status_check'
            ) THEN
                ALTER TABLE audio_files DROP CONSTRAINT audio_files_status_check;
            END IF;
            ALTER TABLE audio_files ADD CONSTRAINT audio_files_status_check
                CHECK (status IN ('uploading', 'processing', 'ready', 'error', 'deleted'));
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS audio_tags (
            audio_id INTEGER NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (audio_id, tag)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audio_usage (
            id SERIAL PRIMARY KEY,
            audio_id INTEGER NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
            call_id INTEGER REFERENCES call_results(id) ON DELETE SET NULL,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_audio_files_status ON audio_files(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audio_files_deleted_at ON audio_files(deleted_at) WHERE deleted_at IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audio_tags_audio ON audio_tags(audio_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audio_usage_audio ON audio_usage(audio_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audio_usage")
    op.execute("DROP TABLE IF EXISTS audio_tags")
    op.execute("""
        ALTER TABLE audio_files
            DROP CONSTRAINT IF EXISTS audio_files_status_check,
            DROP CONSTRAINT IF EXISTS audio_files_converted_from_id_fkey,
            DROP COLUMN IF EXISTS file_name,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS sample_rate,
            DROP COLUMN IF EXISTS channels,
            DROP COLUMN IF EXISTS bitrate,
            DROP COLUMN IF EXISTS converted_from_id,
            DROP COLUMN IF EXISTS tts_text,
            DROP COLUMN IF EXISTS tts_voice,
            DROP COLUMN IF EXISTS tts_model,
            DROP COLUMN IF EXISTS tts_speed,
            DROP COLUMN IF EXISTS view_count,
            DROP COLUMN IF EXISTS usage_count,
            DROP COLUMN IF EXISTS last_used_at,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS deleted_at
    """)
    op.execute("ALTER TABLE audio_files ALTER COLUMN duration TYPE INTEGER USING duration::INTEGER")
