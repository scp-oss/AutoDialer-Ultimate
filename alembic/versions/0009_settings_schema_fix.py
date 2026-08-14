"""Fix settings schema drift

sql/schema.sql's `settings` table was missing created_at -
SettingsService.initialize_defaults() (called on first application
startup to seed SYSTEM_SETTINGS) inserts it directly. Every fresh
deployment would fail to seed default settings with
UndefinedColumnError.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE settings
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS created_at")
