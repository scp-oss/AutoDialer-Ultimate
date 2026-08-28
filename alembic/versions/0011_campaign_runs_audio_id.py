"""Add campaign_runs.audio_id to snapshot which audio played during that run

get_campaign_run()'s "X из Y" duration comparison in the run-detail view
always joined against the campaign's CURRENT audio_id - if the campaign's
audio was changed after a run happened, that run's comparison silently
started reflecting the new file's duration instead of what actually played
during that run. Snapshotting audio_id onto campaign_runs at start time
(see start_campaign() in app/services/campaign.py) fixes this going
forward; existing runs get NULL here and the query falls back to the
campaign's current audio_id (COALESCE), preserving today's behavior for
history that predates this column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaign_runs
            ADD COLUMN IF NOT EXISTS audio_id INTEGER
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_campaign_runs_audio'
            ) THEN
                ALTER TABLE campaign_runs
                    ADD CONSTRAINT fk_campaign_runs_audio
                    FOREIGN KEY (audio_id) REFERENCES audio_files(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE campaign_runs DROP CONSTRAINT IF EXISTS fk_campaign_runs_audio")
    op.execute("ALTER TABLE campaign_runs DROP COLUMN IF EXISTS audio_id")
