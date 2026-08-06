"""Initial schema

Applies sql/schema.sql (23 tables, indexes, triggers, functions, views,
default settings/admin user) as the baseline for Alembic-tracked
migrations. sql/schema.sql remains the single source of truth for the
schema (also used directly by install.sh for bare-metal deployments); this
migration reads and applies it rather than duplicating its ~900 lines here,
so both deployment paths always agree on schema state.

Revision ID: 0001
Revises:
Create Date: 2026-08-06
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def _split_sql_statements(sql: str) -> list[str]:
    """
    Split a SQL script into individual statements on top-level `;`,
    treating `$$ ... $$` (used by CREATE FUNCTION bodies) as opaque so
    semicolons inside PL/pgSQL function bodies are not treated as
    statement separators. asyncpg (via SQLAlchemy's async engine) does not
    support multi-statement execute() calls, so each statement must be
    sent individually.
    """
    statements = []
    buf: list[str] = []
    in_dollar_quote = False
    i, n = 0, len(sql)
    while i < n:
        if sql[i:i + 2] == "$$":
            in_dollar_quote = not in_dollar_quote
            buf.append("$$")
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_dollar_quote:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def upgrade() -> None:
    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    for statement in _split_sql_statements(sql):
        op.execute(statement)


def downgrade() -> None:
    # Drops everything in one shot rather than reversing 175 individual
    # statements. alembic_version lives in `public` too, and Alembic
    # deletes this migration's row from it right after downgrade()
    # returns - so it must survive with its data intact, not just exist.
    # Park it in a scratch schema across the DROP/CREATE and move it back.
    op.execute("CREATE SCHEMA IF NOT EXISTS alembic_tmp")
    op.execute("ALTER TABLE alembic_version SET SCHEMA alembic_tmp")
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
    op.execute("ALTER TABLE alembic_tmp.alembic_version SET SCHEMA public")
    op.execute("DROP SCHEMA alembic_tmp")
