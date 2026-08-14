"""Fix users/user_permissions/api_keys schema drift

sql/schema.sql's `users` table was missing phone, department, position,
status, created_by, avatar_url, preferences, notifications, totp_secret,
totp_enabled, totp_recovery_codes, totp_last_used, deleted_at,
login_count, metadata - all read/written by app/services/user.py's
UserService/AuthService (profile, 2FA, soft-delete, custom permissions).
`role` CHECK constraint only allowed 3 of the 6 UserRole enum values
('admin', 'operator', 'viewer') - 'manager'/'api'/'auditor' would have
been rejected by Postgres on every create_user()/update_user() call for
those roles. `user_permissions` (custom per-user Permission grants) and
`api_keys` (API key auth) tables never existed at all - every
create_api_key()/list_api_keys()/verify_api_key() and every custom
permission read/write would fail with UndefinedTableError.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS phone VARCHAR(20),
            ADD COLUMN IF NOT EXISTS department VARCHAR(255),
            ADD COLUMN IF NOT EXISTS position VARCHAR(255),
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS created_by INTEGER,
            ADD COLUMN IF NOT EXISTS avatar_url TEXT,
            ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS notifications JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS totp_secret TEXT,
            ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS totp_recovery_codes JSONB,
            ADD COLUMN IF NOT EXISTS totp_last_used TIMESTAMP,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS login_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'users_created_by_fkey'
            ) THEN
                NULL;
            ELSE
                ALTER TABLE users ADD CONSTRAINT users_created_by_fkey
                    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check'
            ) THEN
                ALTER TABLE users DROP CONSTRAINT users_role_check;
            END IF;
            ALTER TABLE users ADD CONSTRAINT users_role_check
                CHECK (role IN ('admin', 'manager', 'operator', 'viewer', 'api', 'auditor'));
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'users_status_check'
            ) THEN
                ALTER TABLE users DROP CONSTRAINT users_status_check;
            END IF;
            ALTER TABLE users ADD CONSTRAINT users_status_check
                CHECK (status IN ('active', 'inactive', 'blocked', 'pending'));
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            permission VARCHAR(100) NOT NULL,
            PRIMARY KEY (user_id, permission)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(255),
            key_hash VARCHAR(255) UNIQUE NOT NULL,
            key_prefix VARCHAR(20),
            permissions JSONB DEFAULT '[]',
            ip_whitelist JSONB,
            is_active BOOLEAN DEFAULT TRUE,
            last_used_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at) WHERE deleted_at IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS user_permissions")
    op.execute("""
        ALTER TABLE users
            DROP CONSTRAINT IF EXISTS users_status_check,
            DROP CONSTRAINT IF EXISTS users_role_check,
            DROP CONSTRAINT IF EXISTS users_created_by_fkey,
            DROP COLUMN IF EXISTS phone,
            DROP COLUMN IF EXISTS department,
            DROP COLUMN IF EXISTS position,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS created_by,
            DROP COLUMN IF EXISTS avatar_url,
            DROP COLUMN IF EXISTS preferences,
            DROP COLUMN IF EXISTS notifications,
            DROP COLUMN IF EXISTS totp_secret,
            DROP COLUMN IF EXISTS totp_enabled,
            DROP COLUMN IF EXISTS totp_recovery_codes,
            DROP COLUMN IF EXISTS totp_last_used,
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS login_count,
            DROP COLUMN IF EXISTS metadata
    """)
