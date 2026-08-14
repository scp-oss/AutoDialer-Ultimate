"""Fix campaigns/campaign_tags and call_results/call_tags/call_events/call_transcriptions schema drift

sql/schema.sql's `campaigns` table was missing priority, dial_mode,
call_timeout, answer_timeout, caller_id_number, paused_at, stopped_at,
metadata - all read/written by app/services/campaign.py's CampaignService
(DialerSettingsSchema maps onto these columns). `campaign_tags` never
existed, breaking every campaign tag operation.

`call_results` was missing direction, dtmf_digits, wait_time,
recording_size, tags, notes - read/written by app/services/call_result.py's
CallResultService.save_call_result()/list_calls()/get_call(). Confirmed
live: CampaignService.get_campaign() failed with UndefinedColumnError on
`cr.wait_time` inside its call_results JOIN for campaign stats, before this
fix was applied. `call_tags`/`call_events`/`call_transcriptions` never
existed at all. `campaign_contacts` was also missing `last_call_status`,
written by the same `_update_campaign_progress()`.

Also fixes a real asyncpg bug found while live-testing this: both
`_update_contact_stats()` and `_update_campaign_progress()` reuse `$1` in
a plain column assignment (`last_call_status = $1`) and inside a
`CASE WHEN $1 IN (...)` comparison against string literals in the same
statement - asyncpg's prepared-statement type inference deduces two
different types for the one parameter (`character varying` from the
column, `text` from the literal comparison) and raises
`AmbiguousParameterError: inconsistent types deduced for parameter $1`.
Fixed in app/services/call_result.py by casting the CASE usage to
`$1::VARCHAR` so both sites agree.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
            ADD COLUMN IF NOT EXISTS dial_mode VARCHAR(20) DEFAULT 'predictive',
            ADD COLUMN IF NOT EXISTS call_timeout INTEGER DEFAULT 30,
            ADD COLUMN IF NOT EXISTS answer_timeout INTEGER DEFAULT 30,
            ADD COLUMN IF NOT EXISTS caller_id_number VARCHAR(20),
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS paused_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS stopped_at TIMESTAMP
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'campaigns_priority_check'
            ) THEN
                ALTER TABLE campaigns DROP CONSTRAINT campaigns_priority_check;
            END IF;
            ALTER TABLE campaigns ADD CONSTRAINT campaigns_priority_check
                CHECK (priority IN ('low', 'normal', 'high', 'critical'));
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'campaigns_dial_mode_check'
            ) THEN
                ALTER TABLE campaigns DROP CONSTRAINT campaigns_dial_mode_check;
            END IF;
            ALTER TABLE campaigns ADD CONSTRAINT campaigns_dial_mode_check
                CHECK (dial_mode IN ('predictive', 'progressive', 'preview', 'power'));
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_tags (
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (campaign_id, tag)
        )
    """)
    op.execute("ALTER TABLE campaign_contacts ADD COLUMN IF NOT EXISTS last_call_status VARCHAR(50)")

    op.execute("""
        ALTER TABLE call_results
            ADD COLUMN IF NOT EXISTS direction VARCHAR(20) DEFAULT 'outbound',
            ADD COLUMN IF NOT EXISTS dtmf_digits VARCHAR(50),
            ADD COLUMN IF NOT EXISTS wait_time INTEGER,
            ADD COLUMN IF NOT EXISTS recording_size INTEGER,
            ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS notes TEXT
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'call_results_direction_check'
            ) THEN
                ALTER TABLE call_results DROP CONSTRAINT call_results_direction_check;
            END IF;
            ALTER TABLE call_results ADD CONSTRAINT call_results_direction_check
                CHECK (direction IN ('outbound', 'inbound'));
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS call_tags (
            call_id INTEGER NOT NULL REFERENCES call_results(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            PRIMARY KEY (call_id, tag)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS call_events (
            id SERIAL PRIMARY KEY,
            call_id INTEGER NOT NULL REFERENCES call_results(id) ON DELETE CASCADE,
            event_type VARCHAR(50) NOT NULL,
            details JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS call_transcriptions (
            id SERIAL PRIMARY KEY,
            call_id INTEGER NOT NULL REFERENCES call_results(id) ON DELETE CASCADE,
            transcription TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_priority ON campaigns(priority)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_campaign_tags_campaign ON campaign_tags(campaign_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_call_tags_call ON call_tags(call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_call_events_call ON call_events(call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_call_transcriptions_call ON call_transcriptions(call_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS call_transcriptions")
    op.execute("DROP TABLE IF EXISTS call_events")
    op.execute("DROP TABLE IF EXISTS call_tags")
    op.execute("""
        ALTER TABLE call_results
            DROP CONSTRAINT IF EXISTS call_results_direction_check,
            DROP COLUMN IF EXISTS direction,
            DROP COLUMN IF EXISTS dtmf_digits,
            DROP COLUMN IF EXISTS wait_time,
            DROP COLUMN IF EXISTS recording_size,
            DROP COLUMN IF EXISTS tags,
            DROP COLUMN IF EXISTS notes
    """)
    op.execute("DROP TABLE IF EXISTS campaign_tags")
    op.execute("ALTER TABLE campaign_contacts DROP COLUMN IF EXISTS last_call_status")
    op.execute("""
        ALTER TABLE campaigns
            DROP CONSTRAINT IF EXISTS campaigns_priority_check,
            DROP CONSTRAINT IF EXISTS campaigns_dial_mode_check,
            DROP COLUMN IF EXISTS priority,
            DROP COLUMN IF EXISTS dial_mode,
            DROP COLUMN IF EXISTS call_timeout,
            DROP COLUMN IF EXISTS answer_timeout,
            DROP COLUMN IF EXISTS caller_id_number,
            DROP COLUMN IF EXISTS metadata,
            DROP COLUMN IF EXISTS paused_at,
            DROP COLUMN IF EXISTS stopped_at
    """)
