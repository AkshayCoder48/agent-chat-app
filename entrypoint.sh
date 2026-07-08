#!/bin/bash
# Entrypoint for Hugging Face Spaces — bundles PostgreSQL inside the container.
#
# HF Spaces requires the container to run as non-root user 1000. This script
# runs PostgreSQL as user 1000 directly (no su needed) by initializing the
# data directory under /home/appuser and using the postgres binary with -U.
#
# Steps:
#   1. Initialize PostgreSQL data dir (first boot only)
#   2. Start Postgres on port 5432 (listens on localhost only)
#   3. Create the database
#   4. Run Alembic migrations
#   5. Seed an admin user
#   6. Start the FastAPI server on port 7860 (HF Spaces default)

set -e

export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
export PGUSER="${POSTGRES_USER:-postgres}"
export PGDATABASE="${POSTGRES_DB:-agent_chat_app}"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"

# If POSTGRES_HOST is set to something other than localhost, skip bundled Postgres.
USE_BUNDLED_PG=1
if [ -n "$POSTGRES_HOST" ] && [ "$POSTGRES_HOST" != "localhost" ] && [ "$POSTGRES_HOST" != "127.0.0.1" ]; then
  USE_BUNDLED_PG=0
  echo "[entrypoint] External Postgres detected at $POSTGRES_HOST:$PGPORT — skipping bundled Postgres."
fi

if [ "$USE_BUNDLED_PG" = "1" ]; then
  PG_DATA="/home/appuser/pg/data"
  PG_LOG="/home/appuser/pg/postgres.log"
  mkdir -p /home/appuser/pg

  if [ ! -d "$PG_DATA" ]; then
    echo "[entrypoint] Initializing PostgreSQL data dir at $PG_DATA…"
    initdb -D "$PG_DATA" -U "$PGUSER" --auth=trust --encoding=UTF8
    echo "local   all   all   trust" > "$PG_DATA/pg_hba.conf"
    echo "host    all   all   127.0.0.1/32   trust" >> "$PG_DATA/pg_hba.conf"
    echo "host    all   all   ::1/128        trust" >> "$PG_DATA/pg_hba.conf"
  else
    echo "[entrypoint] PostgreSQL data dir already exists at $PG_DATA — skipping initdb."
    rm -f "$PG_DATA/postmaster.pid"
  fi

  echo "[entrypoint] Starting PostgreSQL…"
  if ! pg_ctl -D "$PG_DATA" -l "$PG_LOG" -w -t 60 -o \
      "-c listen_addresses=127.0.0.1 -p $PGPORT \
       -c unix_socket_directories=/tmp \
       -c dynamic_shared_memory_type=mmap \
       -c shared_buffers=32MB \
       -c max_connections=20 \
       -c work_mem=4MB" start; then
    echo "[entrypoint] pg_ctl failed to start Postgres. Dumping postgres.log:"
    cat "$PG_LOG" 2>/dev/null || echo "(no postgres.log found)"
    exit 1
  fi
  echo "[entrypoint] PostgreSQL started successfully."

  for i in $(seq 1 30); do
    if pg_isready -h 127.0.0.1 -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
      echo "[entrypoint] Postgres is ready."
      break
    fi
    echo "[entrypoint] Waiting for Postgres… ($i/30)"
    sleep 1
  done

  if ! pg_isready -h 127.0.0.1 -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
    echo "[entrypoint] Postgres did not become ready in 30s. Dumping postgres.log:"
    cat "$PG_LOG" 2>/dev/null || echo "(no postgres.log found)"
    exit 1
  fi

  if ! psql -h 127.0.0.1 -p "$PGPORT" -U "$PGUSER" -lqt | cut -d'|' -f1 | grep -qw "$PGDATABASE"; then
    echo "[entrypoint] Creating database $PGDATABASE…"
    createdb -h 127.0.0.1 -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
  else
    echo "[entrypoint] Database $PGDATABASE already exists."
  fi
fi

echo "[entrypoint] Applying Alembic migrations…"
cd /app/backend
alembic upgrade head || echo "[entrypoint] WARNING: Alembic migration failed, continuing anyway"

if [ -n "$SEED_ADMIN_EMAIL" ] && [ -n "$SEED_ADMIN_PASSWORD" ]; then
  echo "[entrypoint] Seeding admin user $SEED_ADMIN_EMAIL…"
  python -m cli.commands user create-admin \
    --email "$SEED_ADMIN_EMAIL" --password "$SEED_ADMIN_PASSWORD" || \
    echo "[entrypoint] WARNING: Admin seed failed (may already exist)"
fi

echo "[entrypoint] Starting FastAPI on 0.0.0.0:7860…"
exec python -u -m cli.commands server run --host 0.0.0.0 --port 7860
