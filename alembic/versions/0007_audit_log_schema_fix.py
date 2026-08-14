"""Fix audit_log schema drift

sql/schema.sql's `audit_log` table was missing user_role, severity,
entity_name, changes, request_method, request_path, correlation_id,
request_id, session_id, status, error_message, metadata - all
read/written by app/services/audit.py's AuditService.log()/log_batch()
(INSERT), and read back by get_audit_log()/_row_to_response()/
list_audit_logs() filtering on severity/status/correlation_id/session_id.
Every call to AuditService.log() - i.e. every audited action anywhere in
the system - would fail with UndefinedColumnError on INSERT.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit_log
            ADD COLUMN IF NOT EXISTS user_role VARCHAR(20),
            ADD COLUMN IF NOT EXISTS severity VARCHAR(20) DEFAULT 'info',
            ADD COLUMN IF NOT EXISTS entity_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS changes JSONB,
            ADD COLUMN IF NOT EXISTS request_method VARCHAR(10),
            ADD COLUMN IF NOT EXISTS request_path VARCHAR(500),
            ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS request_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS session_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'success',
            ADD COLUMN IF NOT EXISTS error_message TEXT,
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'audit_log_severity_check'
            ) THEN
                ALTER TABLE audit_log DROP CONSTRAINT audit_log_severity_check;
            END IF;
            ALTER TABLE audit_log ADD CONSTRAINT audit_log_severity_check
                CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'));
        END $$;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_correlation ON audit_log(correlation_id) WHERE correlation_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_severity ON audit_log(severity)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id) WHERE entity_type IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_session ON audit_log(session_id) WHERE session_id IS NOT NULL")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE audit_log
            DROP CONSTRAINT IF EXISTS audit_log_severity_check,
            DROP COLUMN IF EXISTS user_role,
            DROP COLUMN IF EXISTS severity,
            DROP COLUMN IF EXISTS entity_name,
            DROP COLUMN IF EXISTS changes,
            DROP COLUMN IF EXISTS request_method,
            DROP COLUMN IF EXISTS request_path,
            DROP COLUMN IF EXISTS correlation_id,
            DROP COLUMN IF EXISTS request_id,
            DROP COLUMN IF EXISTS session_id,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS error_message,
            DROP COLUMN IF EXISTS metadata
    """)
