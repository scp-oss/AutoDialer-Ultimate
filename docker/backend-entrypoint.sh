#!/bin/sh
set -e

# Applies pending Alembic migrations before starting the API server.
# Safe to run on every container start/restart: Alembic no-ops when the
# database is already at head (see alembic/versions/0001_initial_schema.py).
echo "Running database migrations (alembic upgrade head)..."
alembic upgrade head

exec "$@"
