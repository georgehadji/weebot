#!/bin/sh
# Weebot — Docker entrypoint
# Runs database migrations, then execs the CMD process.
set -e

# ── Run database migrations ──────────────────────────────────────────
# Idempotent: no-op if DB is already current, creates + migrates if fresh.
echo "==> Running alembic migrations..."
alembic upgrade head
echo "==> Migrations done."

# ── Exec the container CMD ───────────────────────────────────────────
# "exec" ensures signals (SIGTERM for graceful shutdown) reach the process.
exec "$@"
