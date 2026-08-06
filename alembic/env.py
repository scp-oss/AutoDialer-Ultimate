#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alembic environment for AutoDialer Ultimate.

The application's runtime data-access layer (app.core.database) talks to
PostgreSQL directly via asyncpg with hand-written SQL (ConnectionPool /
QueryBuilder / BaseRepository) rather than the SQLAlchemy ORM - asyncpg's
native connection pooling and prepared-statement caching matter for a
dialer pushing hundreds of concurrent queries. There is therefore no
SQLAlchemy metadata to autogenerate against; migrations here are plain SQL
(see alembic/versions/0001_initial_schema.py), and this file exists only to
give that raw SQL proper version tracking, rollback, and a single
`alembic upgrade head` entry point instead of manually running .sql files.

The DB connection is built from the same Settings used by the application
(app.core.config), so one .env configures both.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    auth = f"{settings.DB_USER}:{settings.DB_PASSWORD}" if settings.DB_PASSWORD else settings.DB_USER
    return f"postgresql+asyncpg://{auth}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"


def run_migrations_offline() -> None:
    """Generate SQL script without a live DB connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(get_url(), poolclass=None)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
