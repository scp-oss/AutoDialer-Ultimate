"""Raise campaigns.call_timeout default from 30 to 90 and backfill existing rows

campaigns.call_timeout (added in 0004) was persisted through the API but
never actually read by app/services/dialer.py when placing a call - it
always used the global settings.CALL_TIMEOUT for the AMI Originate Timeout,
and the dialplan's own [globals] CALL_TIMEOUT for Dial()'s ring timeout.
That made the stored value (always 30, the only default ever set - there
was no UI field to change it) completely inert.

Wiring it into dialer.py now makes it real. Since every existing campaign
already has call_timeout=30 stored (never touched, since it was dead code),
turning that into a live value would immediately reintroduce the exact bug
fixed today: real calls getting torn down by Asterisk around 30 seconds in,
mid-IVR, well before AMD+pitch+menu+DTMF-wait can finish (see the global
CALL_TIMEOUT 30->90 fix in the dialplan/config for the full story). Backfill
existing rows to 90 (the same value the global default was raised to) so
this migration alone can't reintroduce that regression.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaigns
            ALTER COLUMN call_timeout SET DEFAULT 90
    """)
    op.execute("""
        UPDATE campaigns SET call_timeout = 90 WHERE call_timeout = 30
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE campaigns
            ALTER COLUMN call_timeout SET DEFAULT 30
    """)
